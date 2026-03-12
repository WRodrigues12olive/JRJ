from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from .models import CustomUser
from logistics.models import MotoboyProfile
from logistics.validators import validate_cnh, validate_plate, clean_cnh, clean_plate

def custom_logout(request):
    logout(request)
    return redirect('login')

@login_required
def register_user_view(request):
    if request.user.type not in ['ADMIN', 'DISPATCHER'] and not request.user.is_superuser:
        messages.error(request, 'Você não tem permissão para cadastrar usuários.')
        return redirect('root')

    if request.method == 'POST':
        user_type = request.POST.get('user_type', CustomUser.Types.COMPANY)
        nome_ou_empresa = request.POST.get('name') 
        documento = request.POST.get('document') 
        usuario = request.POST.get('username')
        telefone = request.POST.get('phone')
        email = request.POST.get('email')
        senha = request.POST.get('password')

        if CustomUser.objects.filter(username=usuario).exists():
            messages.error(request, '❌ Este nome de utilizador de login já está em uso.')
            return render(request, 'accounts/register_user.html')
            
        if CustomUser.objects.filter(email=email).exists():
            messages.error(request, '❌ Este e-mail já está cadastrado no sistema.')
            return render(request, 'accounts/register_user.html')

        user = CustomUser.objects.create_user(
            username=usuario,
            email=email,
            password=senha,
            first_name=nome_ou_empresa,
            type=user_type,             
            cnpj_cpf=documento,         
            phone=telefone
        )
        
        if user_type == CustomUser.Types.MOTOBOY:
            cnh_input = (request.POST.get('cnh_number') or '').strip()
            placa_input = (request.POST.get('vehicle_plate') or '').strip()
            cnh_final = 'Pendente'
            placa_final = 'Pendente'
            if cnh_input:
                ok, err = validate_cnh(cnh_input)
                if not ok:
                    user.delete()
                    messages.error(request, f'❌ {err}')
                    return render(request, 'accounts/register_user.html')
                cnh_final = clean_cnh(cnh_input) or 'Pendente'
            if placa_input:
                ok, err = validate_plate(placa_input)
                if not ok:
                    user.delete()
                    messages.error(request, f'❌ {err}')
                    return render(request, 'accounts/register_user.html')
                placa_final = clean_plate(placa_input) or 'Pendente'
            MotoboyProfile.objects.create(
                user=user,
                category=request.POST.get('motoboy_category', 'TELE'),
                cnh_number=cnh_final,
                vehicle_plate=placa_final
            )
        
        messages.success(request, f'✅ Usuário "{user.username}" cadastrado com sucesso!')
        return redirect('register_user')

    return render(request, 'accounts/register_user.html')