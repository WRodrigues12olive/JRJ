# orders/forms.py
from django import forms
from .models import ServiceOrder

# Deixe apenas o esqueleto para não quebrar as importações
class ServiceOrderForm(forms.ModelForm):
    class Meta:
        model = ServiceOrder
        fields = ['priority'] # Campo que ainda existe