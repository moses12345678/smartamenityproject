from django.contrib import admin
from django import forms
from django.db import models
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.core.exceptions import ValidationError
import random
import uuid

from .models import (
    Amenity,
    AmenitySession,
    City,
    ContactRequest,
    Property,
    ResidentProfile,
    State,
    User,
)


class AmenityInline(admin.TabularInline):
    model = Amenity
    extra = 0
    fields = ("name", "type", "capacity", "is_active", "open_time", "close_time")
    readonly_fields = ()
    formfield_overrides = {
        models.TimeField: {
            "widget": forms.TimeInput(format="%H:%M", attrs={"type": "time"})
        }
    }


class PropertyResidentInline(admin.TabularInline):
    model = ResidentProfile
    extra = 0
    fields = (
        "user",
        "last_temp_code_display",
        "unit_number",
        "is_verified",
        "is_active",
        "ended_at",
        "address_line1",
        "address_line2",
    )
    readonly_fields = ("ended_at", "last_temp_code_display")
    autocomplete_fields = ("user",)

    def last_temp_code_display(self, obj):
        if not obj or not getattr(obj, "user", None):
            return ""
        return getattr(obj.user, "last_temp_code", "") or ""

    last_temp_code_display.short_description = "Temp code"


class ResidentProfileInline(admin.StackedInline):
    model = ResidentProfile
    can_delete = False
    fk_name = "user"
    extra = 0
    fields = (
        "property",
        "last_temp_code_display",
        "unit_number",
        "is_verified",
        "is_active",
        "address_line1",
        "address_line2",
    )
    readonly_fields = ("last_temp_code_display",)

    def last_temp_code_display(self, obj):
        if not obj or not getattr(obj, "user", None):
            return ""
        return getattr(obj.user, "last_temp_code", "") or ""

    last_temp_code_display.short_description = "Temp code"


class TempCodeWidget(forms.TextInput):
    template_name = "django/forms/widgets/text.html"

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        attrs.setdefault("autocomplete", "off")
        html = super().render(name, value, attrs, renderer)
        element_id = attrs.get("id", f"id_{name}")
        button = format_html(
            '<button type="button" class="button" style="margin-left:6px;" '
            'onclick="(function(){{var i=document.getElementById(\'{id}\');'
            "if(!i)return;var c=('0000' + Math.floor(Math.random()*10000)).slice(-4);"
            "i.value=c; i.focus(); i.select();}})();\">Generate</button>",
            id=element_id,
        )
        return format_html("{}{}", html, button)


class InviteTokenWidget(forms.TextInput):
    template_name = "django/forms/widgets/text.html"

    def render(self, name, value, attrs=None, renderer=None):
        html = super().render(name, value, attrs, renderer)
        element_id = (attrs or {}).get("id", f"id_{name}")
        js = (
            "const i=document.getElementById('%(id)s');"
            "if(!i) return;"
            "const gen=(window.crypto && window.crypto.randomUUID) ? window.crypto.randomUUID() : "
            "'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,function(c){"
            "const r=Math.random()*16|0,v=c==='x'?r:(r&0x3|0x8);return v.toString(16);});"
            "i.value=gen; setTimeout(function(){i.focus(); i.select();},0);"
        ) % {"id": element_id}
        button = (
            '<button type="button" class="button" '
            'style="margin-left:6px;" '
            'onmousedown="event.preventDefault();" '
            f'onclick="(function(){{{js}}})()">Generate</button>'
        )
        return mark_safe(f"{html}{button}")


class UserAdminForm(forms.ModelForm):
    temp_code = forms.CharField(
        label="Temporary code",
        required=False,
        help_text="Click Generate for a 4-digit code. Sets password and forces change on first login.",
        widget=TempCodeWidget,
    )

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "is_staff", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Allow blank role so superusers can stay role-less
        self.fields["role"].required = False

    def clean_temp_code(self):
        code = (self.cleaned_data.get("temp_code") or "").strip()
        if not code:
            # generate later if still empty
            return ""
        if not (code.isdigit() and len(code) == 4):
            raise ValidationError("Temporary code must be exactly 4 digits.")
        return code

    def save(self, commit=True):
        user = super().save(commit=False)
        code = (self.cleaned_data.get("temp_code") or "").strip()
        if not code:
            code = f"{random.randint(0, 9999):04d}"
        if code:
            user.set_password(code)
            user.last_temp_code = code
            user.must_change_password = True
        if commit:
            user.save()
            self.save_m2m()
        return user


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "first_name", "last_name", "role", "last_temp_code", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name", "role")
    ordering = ("email",)
    list_filter = ("role", "is_staff", "is_active")
    form = UserAdminForm
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "role",
                    "is_staff",
                    "is_active",
                    "temp_code",
                    "last_temp_code",
                )
            },
        ),
    )
    readonly_fields = ("last_temp_code",)
    inlines = [ResidentProfileInline]
    actions = ("make_managers", "make_tenants")

    @admin.action(description="Mark selected users as Managers")
    def make_managers(self, request, queryset):
        queryset.update(role=User.Role.MANAGER)

    @admin.action(description="Mark selected users as Tenants")
    def make_tenants(self, request, queryset):
        queryset.update(role=User.Role.TENANT)


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "state")
    search_fields = ("name",)
    list_filter = ("state",)


class PropertyAdminForm(forms.ModelForm):
    invite_token = forms.CharField(
        required=False,
        help_text="Click Generate to create a fresh invite code. Leave blank to keep the current one.",
        widget=InviteTokenWidget,
    )

    class Meta:
        model = Property
        fields = "__all__"

    def clean_invite_token(self):
        raw = (self.cleaned_data.get("invite_token") or "").strip()
        if not raw:
            if self.instance and self.instance.pk and self.instance.invite_token:
                return self.instance.invite_token
            return uuid.uuid4()
        try:
            return uuid.UUID(raw)
        except ValueError as exc:
            raise ValidationError("Enter a valid UUID or click Generate.") from exc


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "total_units", "is_verified", "invite_token", "invite_link_display")
    search_fields = ("name", "slug", "invite_token")
    list_filter = ("city", "is_verified")
    readonly_fields = ("invite_link_display",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [AmenityInline, PropertyResidentInline]
    form = PropertyAdminForm

    actions = ("regenerate_invite_tokens",)

    def invite_link_display(self, obj):
        link = obj.invite_link
        return mark_safe(f'<a href="{link}" target="_blank">{link}</a>')

    invite_link_display.short_description = "Invite Link"

    @admin.action(description="Regenerate invite tokens")
    def regenerate_invite_tokens(self, request, queryset):
        for prop in queryset:
            prop.invite_token = uuid.uuid4()
            prop.save(update_fields=["invite_token"])
        self.message_user(request, f"Regenerated invite tokens for {queryset.count()} properties.")


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display = ("name", "property", "type", "capacity", "is_active", "open_time", "close_time")
    list_filter = ("property", "type", "is_active")
    search_fields = ("name",)


@admin.register(ResidentProfile)
class ResidentProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "property",
        "unit_number",
        "address_line1",
        "is_verified",
        "is_active",
    )
    list_filter = ("property", "is_verified", "is_active")
    search_fields = ("user__email", "unit_number", "address_line1", "address_line2")
    actions = ("deactivate_residents", "activate_residents")

    @admin.action(description="Deactivate selected residents")
    def deactivate_residents(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Activate selected residents")
    def activate_residents(self, request, queryset):
        queryset.update(is_active=True)


@admin.register(AmenitySession)
class AmenitySessionAdmin(admin.ModelAdmin):
    list_display = ("resident", "amenity", "guest_count", "check_in_time", "check_out_time", "is_active")
    list_filter = ("amenity", "is_active")
    search_fields = ("resident__user__email",)


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "email", "phone", "status", "created_at")
    search_fields = ("first_name", "last_name", "email", "phone")
    list_filter = ("status", "created_at")
