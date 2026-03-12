# logistics/validators.py
import re


# CNH (Brasil): exatamente 11 dígitos numéricos
CNH_LENGTH = 11
CNH_PATTERN = re.compile(r"^\d{11}$")


def validate_cnh(value):
    """
    Valida o número da CNH.
    - Apenas dígitos (0-9).
    - Exatamente 11 caracteres.
    Retorna (True, None) se válido, (False, mensagem_erro) se inválido.
    """
    if not value or not isinstance(value, str):
        return False, "CNH é obrigatória."
    cleaned = value.strip().replace(" ", "").replace(".", "").replace("-", "")
    if not cleaned.isdigit():
        return False, "CNH deve conter apenas números (11 dígitos)."
    if len(cleaned) != CNH_LENGTH:
        return False, f"CNH deve ter exatamente {CNH_LENGTH} dígitos."
    return True, None


def clean_cnh(value):
    """Remove espaços e caracteres não numéricos; retorna string com no máximo 11 dígitos ou None."""
    if not value or not isinstance(value, str):
        return None
    cleaned = "".join(c for c in value if c.isdigit())[:CNH_LENGTH]
    return cleaned if cleaned else None


# Placa (Brasil): 7 caracteres - Mercosul (ABC1D23) ou antiga (ABC1234)
PLACA_LENGTH = 7
# Mercosul: 3 letras + 1 número + 1 letra + 2 números
PLACA_MERCOSUL = re.compile(r"^[A-Za-z]{3}[0-9][A-Za-z][0-9]{2}$")
# Antiga: 3 letras + 4 números
PLACA_ANTIGA = re.compile(r"^[A-Za-z]{3}[0-9]{4}$")


def validate_plate(value):
    """
    Valida a placa do veículo.
    - Apenas letras e números (sem hífen).
    - Exatamente 7 caracteres.
    - Formato: Mercosul (ABC1D23) ou antiga (ABC1234).
    Retorna (True, None) se válido, (False, mensagem_erro) se inválido.
    """
    if not value or not isinstance(value, str):
        return False, "Placa do veículo é obrigatória."
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if len(cleaned) != PLACA_LENGTH:
        return False, f"Placa deve ter exatamente {PLACA_LENGTH} caracteres (letras e números)."
    if not cleaned.isalnum():
        return False, "Placa deve conter apenas letras e números."
    if PLACA_MERCOSUL.match(cleaned) or PLACA_ANTIGA.match(cleaned):
        return True, None
    return False, "Placa inválida. Use formato Mercosul (ex: ABC1D23) ou antigo (ex: ABC1234)."


def clean_plate(value):
    """Remove espaços e hífens; deixa só letras e números, 7 caracteres; retorna em maiúsculas ou None."""
    if not value or not isinstance(value, str):
        return None
    cleaned = "".join(c for c in value.upper() if c.isalnum())[:PLACA_LENGTH]
    return cleaned if len(cleaned) == PLACA_LENGTH else None
