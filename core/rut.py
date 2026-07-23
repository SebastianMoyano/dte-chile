"""
core/rut.py

Validador y utilidades para RUT (Rol Único Tributario) de Chile.

El RUT chileno tiene el formato: XX.XXX.XXX-V o XXXXXXX-V
donde V es el dígito verificador calculado con algoritmo módulo 11.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple


def calcular_dv(rut_numero: int | str) -> str:
    """
    Calcula el dígito verificador de un RUT usando el algoritmo módulo 11.

    Args:
        rut_numero: Número del RUT sin puntos ni guión, ni DV.

    Returns:
        El dígito verificador como string (0-9 o 'K').

    Example:
        >>> calcular_dv(12345678)
        '9'
        >>> calcular_dv("12345678")
        '9'
    """
    rut_str = str(rut_numero).replace(".", "").replace("-", "").strip()
    rut_int = int(rut_str)

    suma = 0
    multiplicador = 2

    while rut_int > 0:
        digito = rut_int % 10
        suma += digito * multiplicador
        rut_int //= 10
        multiplicador = multiplicador + 1 if multiplicador < 7 else 2

    resto = suma % 11
    dv = 11 - resto

    if dv == 11:
        return "0"
    elif dv == 10:
        return "K"
    else:
        return str(dv)


def validar_rut(rut: str) -> bool:
    """
    Valida un RUT chileno completo (número + dígito verificador).

    Acepta formatos:
    - 12345678-9
    - 123456789
    - 12.345.678-9
    - 12.345.678-K

    Args:
        rut: String con el RUT a validar.

    Returns:
        True si el RUT es válido, False en caso contrario.

    Example:
        >>> validar_rut("12345678-9")
        True
        >>> validar_rut("12.345.678-9")
        True
        >>> validar_rut("12345678-0")
        False
    """
    if not rut:
        return False

    rut_limpio = limpiar_rut(rut)
    if not rut_limpio:
        return False

    partes = rut_limpio.split("-")
    if len(partes) != 2:
        return False

    numero_str, dv_ingresado = partes

    try:
        numero = int(numero_str)
    except ValueError:
        return False

    if numero < 1_000_000:
        return False

    dv_calculado = calcular_dv(numero)
    return dv_ingresado.upper() == dv_calculado.upper()


def limpiar_rut(rut: str) -> str:
    """
    Limpia un RUT quitando puntos y dejando solo el número y DV con guión.

    Args:
        rut: RUT en cualquier formato.

    Returns:
        RUT limpio en formato XXXXXXXX-X, o string vacío si es inválido.

    Example:
        >>> limpiar_rut("12.345.678-9")
        '12345678-9'
        >>> limpiar_rut("123456789")
        '12345678-9'
    """
    if not rut:
        return ""

    rut_sin_puntos = rut.replace(".", "").replace(" ", "")

    if "-" in rut_sin_puntos:
        partes = rut_sin_puntos.split("-")
        if len(partes) == 2:
            numero_str, dv = partes
            try:
                numero = int(numero_str)
                return f"{numero}-{dv.upper()}"
            except ValueError:
                return ""
        return ""

    rut_sin_guion = rut_sin_puntos.replace("-", "")
    if len(rut_sin_guion) < 2:
        return ""

    numero_str = rut_sin_guion[:-1]
    dv = rut_sin_guion[-1]

    try:
        numero = int(numero_str)
        return f"{numero}-{dv.upper()}"
    except ValueError:
        return ""


def formatear_rut(rut: str, con_puntos: bool = True) -> str:
    """
    Formatea un RUT para visualización.

    Args:
        rut: RUT en cualquier formato.
        con_puntos: Si True, agrega puntos de mil. Si False, solo número-DV.

    Returns:
        RUT formateado.

    Example:
        >>> formatear_rut("12345678-9")
        '12.345.678-9'
        >>> formatear_rut("12345678-9", con_puntos=False)
        '12345678-9'
    """
    rut_limpio = limpiar_rut(rut)
    if not rut_limpio:
        return rut

    partes = rut_limpio.split("-")
    numero_str = partes[0]
    dv = partes[1]

    if con_puntos:
        numero_fmt = f"{int(numero_str):,}".replace(",", ".")
        return f"{numero_fmt}-{dv}"
    else:
        return f"{numero_str}-{dv}"


def separar_rut(rut: str) -> Tuple[str, str]:
    """
    Separa un RUT en número y dígito verificador.

    Args:
        rut: RUT en cualquier formato.

    Returns:
        Tupla (numero, dv) donde numero es string sin puntos.

    Example:
        >>> separar_rut("12.345.678-9")
        ('12345678', '9')
    """
    rut_limpio = limpiar_rut(rut)
    if not rut_limpio:
        return ("", "")

    partes = rut_limpio.split("-")
    return (partes[0], partes[1])


def generar_rut_valido(rango_inicio: int = 1_000_000, rango_fin: int = 50_000_000) -> str:
    """
    Genera un RUT válido aleatorio dentro de un rango (solo para testing).

    Args:
        rango_inicio: Número mínimo del RUT.
        rango_fin: Número máximo del RUT.

    Returns:
        RUT válido en formato XXXXXXXX-X.
    """
    import random
    numero = random.randint(rango_inicio, rango_fin)
    dv = calcular_dv(numero)
    return f"{numero}-{dv}"


class RutValidator:
    """
    Validador reutilizable para RUTs chilenos.
    Útil para usar como validator en modelos Pydantic.
    """

    @staticmethod
    def validate(value: str) -> str:
        """
        Valida y normaliza un RUT. Lanza ValueError si es inválido.

        Args:
            value: RUT a validar.

        Returns:
            RUT limpio y validado.

        Raises:
            ValueError: Si el RUT es inválido.
        """
        rut_limpio = limpiar_rut(value)
        if not rut_limpio:
            raise ValueError(f"RUT inválido: formato incorrecto")

        if not validar_rut(rut_limpio):
            raise ValueError(f"RUT inválido: dígito verificador incorrecto")

        return rut_limpio
