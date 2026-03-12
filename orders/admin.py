from django.contrib import admin
from .models import ServiceOrder, OSItem, OSDestination, ItemDistribution

# Isso faz os Itens aparecerem dentro da tela da OS no Admin
class OSItemInline(admin.TabularInline):
    model = OSItem
    extra = 1

# Isso faz os Destinos aparecerem dentro da tela da OS no Admin
class OSDestinationInline(admin.TabularInline):
    model = OSDestination
    extra = 1

@admin.register(ServiceOrder)
class ServiceOrderAdmin(admin.ModelAdmin):
    list_display = ('os_number', 'client', 'status', 'priority', 'created_at')
    list_filter = ('status', 'priority', 'vehicle_type')
    search_fields = ('os_number', 'requester_name')
    readonly_fields = ('os_number',) # Retiramos os campos antigos daqui
    inlines = [OSItemInline, OSDestinationInline]

@admin.register(ItemDistribution)
class ItemDistributionAdmin(admin.ModelAdmin):
    list_display = ('item', 'destination', 'quantity_allocated')