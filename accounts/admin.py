# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    # Adiciona o campo 'type' (Tipo de Usuário) na listagem e no formulário
    fieldsets = UserAdmin.fieldsets + (
        ('Informações do Perfil', {'fields': ('type', 'cnpj_cpf', 'phone')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Informações do Perfil', {'fields': ('type', 'cnpj_cpf', 'phone')}),
    )
    list_display = ('username', 'email', 'type', 'is_active')
    list_filter = ('type', 'is_active')