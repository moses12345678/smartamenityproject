from rest_framework.permissions import BasePermission

from .models import Amenity, ResidentProfile, User


class HasResidentProfile(BasePermission):
    """Ensure the authenticated user has an attached active resident profile."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and hasattr(request.user, "resident_profile")
            and request.user.resident_profile.is_active
        )


class IsResidentOfAmenityProperty(BasePermission):
    """Restrict access to amenities within the resident's property."""

    message = "You do not have access to this property's amenities."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request.user, "resident_profile"):
            return False
        return True

    def has_object_permission(self, request, view, obj):
        amenity = obj if isinstance(obj, Amenity) else None
        if amenity is None and hasattr(view, "get_object"):
            amenity = view.get_object()
        if not amenity:
            return False
        resident: ResidentProfile = request.user.resident_profile
        return resident.is_active and amenity.property_id == resident.property_id


class IsManager(BasePermission):
    """Allow only manager role (superusers always pass)."""

    message = "Manager role required."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return getattr(user, "role", None) == User.Role.MANAGER
