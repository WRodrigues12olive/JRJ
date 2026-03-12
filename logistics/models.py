# logistics/models.py
from django.db import models
from django.conf import settings

class MotoboyProfile(models.Model):
    class Categories(models.TextChoices):
        TELE = 'TELE', 'Tele-Entrega (Tele)'
        DIARIA = 'DIARIA', 'Diária'
        MENSAL = 'MENSAL', 'Mensal'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='motoboy_profile'
    )
    cnh_number = models.CharField(max_length=20, verbose_name="CNH")
    category = models.CharField(max_length=20, choices=Categories.choices)
    vehicle_plate = models.CharField(max_length=10, verbose_name="Placa do Veículo")
    is_available = models.BooleanField(default=True, verbose_name="Disponível?")
    is_absent = models.BooleanField(default=False, verbose_name="Ausente?")
    active_since = models.DateField(auto_now_add=True)
    delivery_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=100.00, verbose_name="Porcentagem por Tele (%)")
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor da Diária (R$)")
    monthly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Mensal (R$)")

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.get_category_display()}"
    
class Vehicle(models.Model):
    owner = models.ForeignKey(MotoboyProfile, on_delete=models.CASCADE, related_name='vehicles')
    plate = models.CharField(max_length=10, verbose_name="Placa")
    brand = models.CharField(max_length=50, verbose_name="Marca/Modelo")
    color = models.CharField(max_length=20, verbose_name="Cor", blank=True)
    
    class Type(models.TextChoices):
        MOTO = 'MOTO', 'Moto'
        CAR = 'CARRO', 'Carro'
        VAN = 'VAN', 'Van'
    
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.MOTO)

    def __str__(self):
        return f"{self.plate} - {self.brand}"
