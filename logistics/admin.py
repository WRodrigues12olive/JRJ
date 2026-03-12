from django.contrib import admin
from .models import MotoboyProfile, Vehicle

@admin.register(MotoboyProfile)
class MotoboyProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'cnh_number', 'is_available', 'category')
    list_filter = ('is_available', 'category')
    search_fields = ('user__username', 'user__first_name', 'cnh_number')

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('plate', 'model', 'brand', 'type')