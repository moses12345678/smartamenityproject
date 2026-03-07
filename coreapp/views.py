from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import Amenity, Property, AmenitySession, ContactRequest
from .permissions import HasResidentProfile, IsResidentOfAmenityProperty
from .serializers import (
    AmenityCheckInSerializer,
    AmenityCheckOutSerializer,
    AmenityStatusSerializer,
    AmenityListSerializer,
    EmailTokenObtainPairSerializer,
    PropertyInviteSerializer,
    PropertyJoinSerializer,
    UserDetailSerializer,
    UserRegistrationSerializer,
    ChangePasswordSerializer,
    ContactRequestSerializer,
)
from .services import calculate_amenity_status

User = get_user_model()


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({"detail": "Self-service registration is disabled. Contact property staff."},
                        status=status.HTTP_403_FORBIDDEN)


class LoginView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [AllowAny]


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"detail": "Password updated."}, status=status.HTTP_200_OK)


class PropertyInviteView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, invite_token):
        property_obj = get_object_or_404(Property.objects.select_related("city__state"), invite_token=invite_token)
        data = PropertyInviteSerializer(property_obj).data
        return Response(data)


class PropertyJoinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PropertyJoinSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(serializer.to_representation(profile), status=status.HTTP_200_OK)


class AmenityBaseView(APIView):
    permission_classes = [IsAuthenticated, HasResidentProfile, IsResidentOfAmenityProperty]

    def get_amenity(self, amenity_id):
        return get_object_or_404(Amenity.objects.select_related("property"), pk=amenity_id)

    def get_resident(self, user):
        return user.resident_profile


class AmenityCheckInView(AmenityBaseView):
    def post(self, request, amenity_id):
        amenity = self.get_amenity(amenity_id)
        resident = self.get_resident(request.user)
        self.check_object_permissions(request, amenity)
        serializer = AmenityCheckInSerializer(
            data=request.data, context={"amenity": amenity, "resident": resident, "request": request}
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return Response(serializer.to_representation(session), status=status.HTTP_201_CREATED)


class AmenityCheckOutView(AmenityBaseView):
    def post(self, request, amenity_id):
        amenity = self.get_amenity(amenity_id)
        resident = self.get_resident(request.user)
        self.check_object_permissions(request, amenity)
        serializer = AmenityCheckOutSerializer(
            data=request.data, context={"amenity": amenity, "resident": resident, "request": request}
        )
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return Response(serializer.to_representation(session), status=status.HTTP_200_OK)


class AmenityStatusView(AmenityBaseView):
    def get(self, request, amenity_id):
        amenity = self.get_amenity(amenity_id)
        self.check_object_permissions(request, amenity)
        status_payload = calculate_amenity_status(amenity)
        resident = getattr(request.user, "resident_profile", None)
        session = None
        if resident:
            session = (
                AmenitySession.objects.filter(amenity=amenity, resident=resident, is_active=True)
                .order_by("-check_in_time")
                .first()
            )
        status_payload["user_has_active_session"] = bool(session)
        status_payload["user_check_in_time"] = session.check_in_time if session else None
        serializer = AmenityStatusSerializer(status_payload)
        return Response(serializer.data)


class LeavePropertyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        resident = getattr(request.user, "resident_profile", None)
        if not resident:
            return Response({"detail": "Resident profile not found."}, status=status.HTTP_400_BAD_REQUEST)
        soft = bool(request.data.get("soft"))
        # Close active sessions
        resident.sessions.filter(is_active=True).update(is_active=False, check_out_time=timezone.now())
        if soft:
            return Response({"detail": "Sessions closed."}, status=status.HTTP_200_OK)
        resident.leave()
        return Response({"detail": "Resident deactivated and sessions closed."}, status=status.HTTP_200_OK)


class PropertyAmenitiesView(APIView):
    permission_classes = [IsAuthenticated, HasResidentProfile]

    def get(self, request, slug):
        resident = request.user.resident_profile
        prop = get_object_or_404(Property, slug=slug)
        if resident.property_id != prop.id or not resident.is_active:
            return Response({"detail": "You do not have access to this property."}, status=status.HTTP_403_FORBIDDEN)
        amenities = prop.amenities.all().order_by("name")
        data = AmenityListSerializer(amenities, many=True).data
        return Response(data)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserDetailSerializer(request.user)
        return Response(serializer.data)


class ContactRequestCreateView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ContactRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact = serializer.save()
        return Response(ContactRequestSerializer(contact).data, status=status.HTTP_201_CREATED)
