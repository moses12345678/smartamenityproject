from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Amenity, AmenitySession, City, Property, ResidentProfile, State, ContactRequest
from .services import calculate_amenity_status, property_timezone

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("id", "email", "password", "first_name", "last_name")

    def validate_password(self, value):
        validate_password(value)
        return value

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(**validated_data, password=password)
        return user

    def to_representation(self, instance):
        data = super().to_representation(instance)
        refresh = RefreshToken.for_user(instance)
        data.update(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        )
        return data


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.EMAIL_FIELD

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = getattr(user, "role", None)
        token["must_change_password"] = getattr(user, "must_change_password", False)
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["role"] = getattr(self.user, "role", None)
        data["must_change_password"] = getattr(self.user, "must_change_password", False)
        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "first_name": self.user.first_name,
            "last_name": self.user.last_name,
            "role": getattr(self.user, "role", None),
            "must_change_password": getattr(self.user, "must_change_password", False),
        }
        return data


class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ("id", "name", "code")


class CitySerializer(serializers.ModelSerializer):
    state = StateSerializer(read_only=True)

    class Meta:
        model = City
        fields = ("id", "name", "state")


class PropertyInviteSerializer(serializers.ModelSerializer):
    city = CitySerializer(read_only=True)

    class Meta:
        model = Property
        fields = ("id", "name", "slug", "address", "city", "total_units", "invite_token", "invite_link", "is_verified")


class PropertyJoinSerializer(serializers.Serializer):
    invite_token = serializers.UUIDField()
    unit_number = serializers.CharField(max_length=32, required=False, allow_blank=True, allow_null=True)
    address_line1 = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        try:
            property_obj = Property.objects.get(invite_token=attrs["invite_token"])
        except Property.DoesNotExist:
            raise NotFound("Invite token not found.")

        attrs["property"] = property_obj

        if hasattr(user, "resident_profile"):
            profile = user.resident_profile
            if profile.property_id == property_obj.id and profile.is_active:
                raise serializers.ValidationError("User already linked to this property.")
            attrs["existing_profile"] = profile

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        user = request.user
        property_obj = validated_data["property"]
        unit_number = validated_data.get("unit_number")
        existing_profile = validated_data.get("existing_profile")
        defaults = {
            "property": property_obj,
            "unit_number": unit_number,
            "is_active": True,
            "ended_at": None,
            "address_line1": validated_data.get("address_line1"),
            "address_line2": validated_data.get("address_line2"),
        }
        if existing_profile:
            for key, value in defaults.items():
                setattr(existing_profile, key, value)
            existing_profile.save()
            profile = existing_profile
        else:
            profile, _created = ResidentProfile.objects.update_or_create(user=user, defaults=defaults)
        return profile

    def to_representation(self, instance):
        return {
            "property": instance.property.name,
            "unit_number": instance.unit_number,
            "address_line1": instance.address_line1,
            "address_line2": instance.address_line2,
            "is_verified": instance.is_verified,
        }


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        new_password = self.validated_data["new_password"]
        user.set_password(new_password)
        user.must_change_password = False
        user.last_temp_code = ""
        user.save(update_fields=["password", "must_change_password", "last_temp_code"])
        return user


class AmenityCheckInSerializer(serializers.Serializer):
    guest_count = serializers.IntegerField(min_value=0, default=0)

    def validate(self, attrs):
        amenity: Amenity = self.context["amenity"]
        resident: ResidentProfile = self.context["resident"]
        guest_count = attrs.get("guest_count", 0)

        if not amenity.is_active:
            raise serializers.ValidationError("Amenity is not active.")

        tz = property_timezone(amenity)
        now_local = timezone.now().astimezone(tz).time()
        if amenity.open_time and amenity.close_time:
            if amenity.open_time <= amenity.close_time:
                open_now = amenity.open_time <= now_local <= amenity.close_time
            else:
                open_now = now_local >= amenity.open_time or now_local <= amenity.close_time
            if not open_now:
                raise serializers.ValidationError("Amenity is currently closed.")

        # Prevent multiple active sessions for same resident and amenity
        if AmenitySession.objects.filter(amenity=amenity, resident=resident, is_active=True).exists():
            raise serializers.ValidationError("Resident already has an active session for this amenity.")

        status = calculate_amenity_status(amenity)
        projected = status["current_count"] + 1 + guest_count
        if amenity.capacity and projected > amenity.capacity:
            raise serializers.ValidationError("Capacity would be exceeded with this check-in.")

        if amenity.max_guests_per_resident is not None and guest_count > amenity.max_guests_per_resident:
            raise serializers.ValidationError("Guest count exceeds per-resident limit.")

        # Compare against *total* active guests (not per check-in) if max_total_guests is set
        if amenity.max_total_guests is not None:
            active_guests = AmenitySession.objects.filter(amenity=amenity, is_active=True).aggregate(
                total=Sum("guest_count")
            )["total"] or 0
            projected_guests = active_guests + guest_count
            if projected_guests > amenity.max_total_guests:
                raise serializers.ValidationError("Total guests would exceed the amenity guest limit.")

        attrs["guest_count"] = guest_count
        return attrs

    def create(self, validated_data):
        amenity: Amenity = self.context["amenity"]
        resident: ResidentProfile = self.context["resident"]
        guest_count = validated_data.get("guest_count", 0)
        return AmenitySession.objects.create(
            amenity=amenity,
            resident=resident,
            guest_count=guest_count,
            is_active=True,
            check_in_time=timezone.now(),
        )

    def to_representation(self, instance):
        return {
            "id": instance.id,
            "amenity": instance.amenity_id,
            "guest_count": instance.guest_count,
            "check_in_time": instance.check_in_time,
            "is_active": instance.is_active,
        }


class AmenityCheckOutSerializer(serializers.Serializer):
    def validate(self, attrs):
        amenity: Amenity = self.context["amenity"]
        resident: ResidentProfile = self.context["resident"]
        session = (
            AmenitySession.objects.filter(amenity=amenity, resident=resident, is_active=True)
            .order_by("-check_in_time")
            .first()
        )

        if not session:
            raise serializers.ValidationError("No active session to check out from.")

        attrs["session"] = session
        return attrs

    def save(self, **kwargs):
        session: AmenitySession = self.validated_data["session"]
        session.check_out_time = timezone.now()
        session.is_active = False
        session.save(update_fields=["check_out_time", "is_active"])
        return session

    def to_representation(self, instance):
        return {
            "id": instance.id,
            "amenity": instance.amenity_id,
            "check_in_time": instance.check_in_time,
            "check_out_time": instance.check_out_time,
            "is_active": instance.is_active,
        }


class AmenityStatusSerializer(serializers.Serializer):
    current_count = serializers.IntegerField()
    capacity = serializers.IntegerField()
    status = serializers.CharField()
    confidence = serializers.IntegerField()
    user_has_active_session = serializers.BooleanField(required=False, default=False)
    user_check_in_time = serializers.DateTimeField(required=False, allow_null=True)

    @classmethod
    def from_amenity(cls, amenity):
        status = calculate_amenity_status(amenity)
        return cls(status).data


class AmenityListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = (
            "id",
            "name",
            "type",
            "capacity",
            "max_guests_per_resident",
            "max_total_guests",
            "is_active",
            "open_time",
            "close_time",
        )


class ResidentProfileSerializer(serializers.ModelSerializer):
    property = PropertyInviteSerializer(read_only=True)

    class Meta:
        model = ResidentProfile
        fields = (
            "property",
            "unit_number",
            "is_verified",
            "is_active",
            "address_line1",
            "address_line2",
        )


class UserDetailSerializer(serializers.ModelSerializer):
    resident_profile = ResidentProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "role", "must_change_password", "resident_profile")


class ContactRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactRequest
        fields = "__all__"
        read_only_fields = ("status", "created_at", "updated_at")
