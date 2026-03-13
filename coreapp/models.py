import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify


class UserManager(BaseUserManager):
    """User manager that uses email as the unique identifier."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address must be provided")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.TENANT)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        # superusers do not carry a tenant/manager role
        extra_fields.setdefault("role", None)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model using email as the login field."""

    class Role(models.TextChoices):
        TENANT = "TENANT", "Tenant"
        MANAGER = "MANAGER", "Manager"

    username = models.CharField(max_length=150, blank=True, null=True)
    email = models.EmailField(unique=True)
    last_temp_code = models.CharField(max_length=32, blank=True, null=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.TENANT)
    EMAIL_FIELD = "email"

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    must_change_password = models.BooleanField(default=False)

    objects = UserManager()

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role"]),
        ]

    def __str__(self):
        return self.email


class State(models.Model):
    name = models.CharField(max_length=128)
    code = models.CharField(max_length=10, unique=True)

    class Meta:
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["name"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class City(models.Model):
    name = models.CharField(max_length=128)
    state = models.ForeignKey(State, on_delete=models.CASCADE, related_name="cities")

    class Meta:
        unique_together = ("name", "state")
        indexes = [
            models.Index(fields=["name", "state"]),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}, {self.state.code}"


class Property(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField()
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="properties")
    total_units = models.PositiveIntegerField(default=0)
    slug = models.SlugField(unique=True)
    invite_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["invite_token"]),
            models.Index(fields=["city"]),
        ]
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Property.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def invite_link(self):
        base_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
        return f"{base_url}/invite/{self.invite_token}"


class Amenity(models.Model):
    class AmenityType(models.TextChoices):
        POOL = "POOL", "Pool"
        GYM = "GYM", "Gym"
        OFFICE = "OFFICE", "Office"
        TENNIS = "TENNIS", "Tennis Court"

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="amenities")
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=10, choices=AmenityType.choices)
    capacity = models.PositiveIntegerField(default=1)
    max_guests_per_resident = models.PositiveIntegerField(null=True, blank=True)
    max_total_guests = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    open_time = models.TimeField()
    close_time = models.TimeField()

    class Meta:
        indexes = [
            models.Index(fields=["property"]),
            models.Index(fields=["type"]),
        ]
        ordering = ["property", "name"]

    def __str__(self):
        return f"{self.name} - {self.property.name}"


class ResidentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="resident_profile")
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="residents")
    unit_number = models.CharField(max_length=32, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["property"]),
            models.Index(fields=["user"]),
            models.Index(fields=["is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(ended_at__isnull=True),
                name="unique_active_resident_per_user",
            )
        ]

    def __str__(self):
        return f"{self.user.email} - {self.property.name}"

    def leave(self, when=None):
        """Mark the resident as having moved out while keeping history."""
        self.ended_at = when or timezone.now()
        self.is_active = False
        self.save(update_fields=["ended_at", "is_active"])


class AmenitySession(models.Model):
    resident = models.ForeignKey(ResidentProfile, on_delete=models.CASCADE, related_name="sessions")
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name="sessions")
    guest_count = models.PositiveIntegerField(default=0)
    check_in_time = models.DateTimeField(default=timezone.now)
    check_out_time = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["amenity", "is_active"]),
            models.Index(fields=["resident", "is_active"]),
            models.Index(fields=["check_in_time"]),
        ]
        ordering = ["-check_in_time"]

    def __str__(self):
        return f"{self.resident.user.email} - {self.amenity.name}"


def default_token_expiry():
    return timezone.now() + timedelta(days=7)


class AmenityCheckInToken(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    amenity = models.ForeignKey(Amenity, on_delete=models.CASCADE, related_name="checkin_tokens")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="issued_checkin_tokens"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_token_expiry)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["token"]),
            models.Index(fields=["amenity"]),
            models.Index(fields=["is_active", "expires_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"QR token for {self.amenity.name} ({self.token})"


class ContactRequest(models.Model):
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    message = models.TextField()
    source = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=32, default="new")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contact_requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} <{self.email}>"
