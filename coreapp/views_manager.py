from datetime import timedelta

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from django.utils import timezone

from .models import Amenity, AmenityCheckInToken, Property, User, ResidentProfile
from .permissions import IsManager
from .serializers import PropertyInviteSerializer
from .serializers_manager import (
    AmenityCheckInTokenSerializer,
    ManagerResidentSerializer,
    ManagerAmenitySerializer,
    ManagerCreateTenantSerializer,
)


class ManagerPropertyListView(APIView):
    permission_classes = [IsAuthenticated, IsManager]

    def get(self, request):
        resident = getattr(request.user, "resident_profile", None)
        if not resident:
            return Response([], status=200)
        prop = resident.property
        data = PropertyInviteSerializer([prop], many=True).data
        return Response(data)


class ManagerResidentListView(APIView):
    permission_classes = [IsAuthenticated, IsManager]

    def get(self, request):
        resident = getattr(request.user, "resident_profile", None)
        if not resident:
            return Response([], status=200)
        qs = (
            resident.property.residents.select_related("user")
            .filter(user__role=User.Role.TENANT)
            .order_by("user__email")
        )
        data = ManagerResidentSerializer(qs, many=True).data
        return Response(data)

    def post(self, request):
        resident = getattr(request.user, "resident_profile", None)
        if not resident:
            return Response({"detail": "No property assigned."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ManagerCreateTenantSerializer(data=request.data, context={"resident": resident})
        serializer.is_valid(raise_exception=True)
        user, tenant_resident, temp_code = serializer.save()
        output = ManagerResidentSerializer(tenant_resident).data
        output["temp_code"] = temp_code
        return Response(output, status=status.HTTP_201_CREATED)


class ManagerResidentDetailView(APIView):
    permission_classes = [IsAuthenticated, IsManager]

    def patch(self, request, resident_id):
        manager_resident = getattr(request.user, "resident_profile", None)
        if not manager_resident:
            return Response({"detail": "No property assigned."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            resident = (
                manager_resident.property.residents.select_related("user")
                .filter(user__role=User.Role.TENANT)
                .get(pk=resident_id)
            )
        except ResidentProfile.DoesNotExist:
            return Response({"detail": "Resident not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data or {}
        regenerated_code = None

        if "unit_number" in data:
            resident.unit_number = data.get("unit_number") or ""
        if "address_line1" in data:
            resident.address_line1 = data.get("address_line1") or ""
        if "address_line2" in data:
            resident.address_line2 = data.get("address_line2") or ""

        if "is_active" in data:
            resident.is_active = bool(data.get("is_active"))

        if data.get("regenerate_temp_code"):
            regenerated_code = f"{timezone.now().microsecond % 10000:04d}"
            u = resident.user
            u.set_password(regenerated_code)
            u.last_temp_code = regenerated_code
            u.must_change_password = True
            u.save(update_fields=["password", "last_temp_code", "must_change_password"])

        resident.save()
        payload = ManagerResidentSerializer(resident).data
        if regenerated_code:
            payload["temp_code"] = regenerated_code
        return Response(payload, status=status.HTTP_200_OK)


class ManagerAmenityListView(APIView):
    permission_classes = [IsAuthenticated, IsManager]

    def get(self, request):
        resident = getattr(request.user, "resident_profile", None)
        if not resident:
            return Response([], status=200)
        qs = Amenity.objects.filter(property=resident.property).order_by("name")
        data = ManagerAmenitySerializer(qs, many=True).data
        return Response(data)

    def patch(self, request, amenity_id=None):
        resident = getattr(request.user, "resident_profile", None)
        if not resident:
            return Response({"detail": "No property assigned."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amenity = Amenity.objects.get(pk=amenity_id, property=resident.property)
        except Amenity.DoesNotExist:
            return Response({"detail": "Amenity not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ManagerAmenitySerializer(amenity, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ManagerAmenityQRCodeView(APIView):
    permission_classes = [IsAuthenticated, IsManager]

    def post(self, request, amenity_id):
        resident = getattr(request.user, "resident_profile", None)
        if not resident:
            return Response({"detail": "No property assigned."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            amenity = Amenity.objects.get(pk=amenity_id, property=resident.property)
        except Amenity.DoesNotExist:
            return Response({"detail": "Amenity not found."}, status=status.HTTP_404_NOT_FOUND)

        expires_in_minutes = request.data.get("expires_in_minutes", 24 * 60)
        try:
            expires_in_minutes = int(expires_in_minutes)
        except (TypeError, ValueError):
            return Response({"detail": "expires_in_minutes must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        if expires_in_minutes <= 0:
            return Response({"detail": "expires_in_minutes must be positive."}, status=status.HTTP_400_BAD_REQUEST)
        # cap at 30 days to prevent forever tokens
        expires_in_minutes = min(expires_in_minutes, 30 * 24 * 60)

        token = AmenityCheckInToken.objects.create(
            amenity=amenity,
            created_by=request.user,
            expires_at=timezone.now() + timedelta(minutes=expires_in_minutes),
        )
        data = AmenityCheckInTokenSerializer(token).data
        return Response(data, status=status.HTTP_201_CREATED)
