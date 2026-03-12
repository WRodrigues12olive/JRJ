from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
    class Types(models.TextChoices):
        ADMIN = 'ADMIN', 'Administrador'
        DISPATCHER = 'DISPATCHER', 'Despachante'
        COMPANY = 'COMPANY', 'Empresa/Cliente'
        MOTOBOY = 'MOTOBOY', 'Motoboy'

    type = models.CharField(
        max_length=50, 
        choices=Types.choices, 
        default=Types.COMPANY, 
        verbose_name="Tipo de Usuário"
    )
    cnpj_cpf = models.CharField(max_length=20, blank=True, verbose_name="CPF/CNPJ")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Telefone")

    def __str__(self):
        return f"{self.username} ({self.get_type_display()})"