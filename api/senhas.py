"""
Hash e verificação de senha com Argon2id (ISS-026), parâmetros padrão do
`argon2-cffi`.

`verificar_senha` NUNCA levanta exceção por causa do hash armazenado: um
hash ilegível ou de formato legado (bcrypt, texto puro, vazio) apenas recusa
o login. E, nesse caso, ainda executa uma verificação completa contra o hash
fictício, para o tempo de resposta não denunciar a conta com hash quebrado.

Os chamadores usam `senhas.verificar_senha(...)` pelo módulo (não
`from api.senhas import verificar_senha`): é o ponto que os testes espiam
para provar que todo login recusado custa exatamente uma verificação.
"""

from functools import lru_cache
from secrets import token_urlsafe

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

_hasher = PasswordHasher()

TAMANHO_MINIMO_SENHA = 8
TAMANHO_MAXIMO_SENHA = 128


class SenhaForaDaPolitica(ValueError):
    """Mensagem fixa: nunca inclui a senha recebida."""

    def __init__(self) -> None:
        super().__init__(
            f"a senha deve ter entre {TAMANHO_MINIMO_SENHA} e {TAMANHO_MAXIMO_SENHA} "
            "caracteres e não pode ser só espaços"
        )


def validar_politica(senha: str) -> None:
    if not TAMANHO_MINIMO_SENHA <= len(senha) <= TAMANHO_MAXIMO_SENHA or not senha.strip():
        raise SenhaForaDaPolitica()


def gerar_hash(senha: str) -> str:
    return _hasher.hash(senha)


@lru_cache(maxsize=1)
def hash_ficticio() -> str:
    """Hash de uma senha aleatória descartada, com os mesmos parâmetros reais."""
    return _hasher.hash(token_urlsafe(32))


def hash_reconhecido(hash_armazenado: str | None) -> bool:
    """True só para hashes Argon2id que esta versão consegue verificar."""
    if not isinstance(hash_armazenado, str) or not hash_armazenado.startswith("$argon2id$"):
        return False
    try:
        return extract_parameters(hash_armazenado).type is Type.ID
    except (InvalidHashError, ValueError):
        return False


def verificar_senha(hash_armazenado: str | None, senha: str) -> bool:
    if hash_reconhecido(hash_armazenado):
        try:
            return _hasher.verify(hash_armazenado, senha)
        except VerifyMismatchError:
            return False
        except (VerificationError, InvalidHashError, ValueError):
            # Parâmetros legíveis, mas sal ou corpo corrompido: o verify falha
            # sem custo nenhum. Cai no caminho do hash ilegível.
            pass
    try:
        _hasher.verify(hash_ficticio(), senha)
    except VerifyMismatchError:
        pass
    return False
