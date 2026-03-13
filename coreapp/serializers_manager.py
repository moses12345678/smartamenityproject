from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import Amenity, AmenityCheckInToken, ResidentProfile, User
from .services import property_timezone


class ManagerResidentSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    last_temp_code = serializers.CharField(source="user.last_temp_code", read_only=True)
    address_line1 = serializers.CharField(read_only=True)
    address_line2 = serializers.CharField(read_only=True)
    active_sessions = serializers.SerializerMethodField()

    class Meta:
        model = ResidentProfile
        fields = (
          "id",
          "email",
          "first_name",
          "last_name",
          "unit_number",
          "address_line1",
          "address_line2",
          "is_verified",
          "is_active",
          "last_temp_code",
          "active_sessions",
        )

    def get_active_sessions(self, obj: ResidentProfile):
        sessions = obj.sessions.filter(is_active=True).select_related("amenity")
        return [
            {
                "amenity": s.amenity.name,
                "amenity_id": s.amenity_id,
                "guest_count": s.guest_count,
                "check_in_time": s.check_in_time,
            }
            for s in sessions
        ]


class AmenityCheckInTokenSerializer(serializers.ModelSerializer):
    amenity_name = serializers.CharField(source="amenity.name", read_only=True)
    qr_value = serializers.SerializerMethodField()
    qr_url = serializers.SerializerMethodField()

    class Meta:
        model = AmenityCheckInToken
        fields = (
            "token",
            "amenity",
            "amenity_name",
            "expires_at",
            "is_active",
            "created_at",
            "qr_value",
            "qr_url",
        )
        read_only_fields = fields

    def get_qr_value(self, obj: AmenityCheckInToken):
        # Raw payload that can be fed directly into a QR generator on the frontend
        return str(obj.token)

    def get_qr_url(self, obj: AmenityCheckInToken):
        base = getattr(settings, "FRONTEND_URL", "").rstrip("/") or "https://app.smartamenity.net"
        return f"{base}/qr-checkin/{obj.token}"


class ManagerAmenitySerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()
    utilization = serializers.SerializerMethodField()
    is_open_now = serializers.SerializerMethodField()

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
            "current",
            "utilization",
            "is_open_now",
        )
        read_only_fields = ("id", "name", "type", "current", "utilization", "is_open_now")

    def get_current(self, obj: Amenity):
        active = obj.sessions.filter(is_active=True)
        guests = active.aggregate(total=Sum("guest_count")).get("total") or 0
        return active.count() + guests

    def get_utilization(self, obj: Amenity):
        capacity = obj.capacity or 0
        if capacity <= 0:
            return 0
        current = self.get_current(obj)
        return max(0, min(100, round((current / capacity) * 100)))

    def get_is_open_now(self, obj: Amenity):
        if obj.open_time is None or obj.close_time is None:
            return obj.is_active
        tz = property_timezone(obj)
        now_local = timezone.now().astimezone(tz).time()
        if obj.open_time <= obj.close_time:
            open_now = obj.open_time <= now_local <= obj.close_time
        else:
            open_now = now_local >= obj.open_time or now_local <= obj.close_time
        return obj.is_active and open_now


class ManagerCreateTenantSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    last_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    unit_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("User with this email already exists.")
        return value

    def create(self, validated_data):
        manager_resident: ResidentProfile = self.context["resident"]
        temp_code = f"{timezone.now().microsecond % 10000:04d}"
        user = User.objects.create_user(
            email=validated_data["email"],
            password=temp_code,
            first_name=validated_data.get("first_name") or "",
            last_name=validated_data.get("last_name") or "",
            role=User.Role.TENANT,
            must_change_password=True,
            last_temp_code=temp_code,
        )
        resident = ResidentProfile.objects.create(
            user=user,
            property=manager_resident.property,
            unit_number=validated_data.get("unit_number") or "",
            is_active=True,
            is_verified=False,
        )
        return user, resident, temp_code
