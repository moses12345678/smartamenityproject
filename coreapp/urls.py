from django.urls import path

from .views import (
    AmenityCheckInView,
    AmenityCheckOutView,
    AmenityStatusView,
    PropertyAmenitiesView,
    LoginView,
    PropertyInviteView,
    PropertyJoinView,
    RefreshView,
    ChangePasswordView,
    RegisterView,
    LeavePropertyView,
    MeView,
)
from .views_manager import (
    ManagerPropertyListView,
    ManagerResidentListView,
    ManagerResidentDetailView,
    ManagerAmenityListView,
)
from .views import ContactRequestCreateView

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="auth-register"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
    path("properties/invite/<uuid:invite_token>/", PropertyInviteView.as_view(), name="property-invite"),
    path("properties/join/", PropertyJoinView.as_view(), name="property-join"),
    path("properties/leave/", LeavePropertyView.as_view(), name="property-leave"),
    path("properties/<slug:slug>/amenities/", PropertyAmenitiesView.as_view(), name="property-amenities"),
    path("amenities/<int:amenity_id>/checkin/", AmenityCheckInView.as_view(), name="amenity-checkin"),
    path("amenities/<int:amenity_id>/checkout/", AmenityCheckOutView.as_view(), name="amenity-checkout"),
    path("amenities/<int:amenity_id>/status/", AmenityStatusView.as_view(), name="amenity-status"),
    path("users/me/", MeView.as_view(), name="user-me"),
    path("contact-requests/", ContactRequestCreateView.as_view(), name="contact-request-create"),
    path("manager/properties/", ManagerPropertyListView.as_view(), name="manager-properties"),
    path("manager/residents/", ManagerResidentListView.as_view(), name="manager-residents"),
    path("manager/residents/<int:resident_id>/", ManagerResidentDetailView.as_view(), name="manager-resident-detail"),
    path("manager/amenities/", ManagerAmenityListView.as_view(), name="manager-amenities"),
    path("manager/amenities/<int:amenity_id>/", ManagerAmenityListView.as_view(), name="manager-amenity-detail"),
]
