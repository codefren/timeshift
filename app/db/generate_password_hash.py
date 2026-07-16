"""
Genera el hash bcrypt de una contraseña, compatible con el login del backend
(usa el mismo passlib.hash.bcrypt que Users.verify_password).

Uso:
    python generate_password_hash.py "MiNuevaPass123"
    python generate_password_hash.py "MiNuevaPass123" --email usuario@ejemplo.com

Si se pasa --email, además imprime el UPDATE SQL listo para ejecutar.
"""
import sys
from passlib.hash import bcrypt


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--email"]
    if not args:
        print('Uso: python generate_password_hash.py "<password>" [--email <correo>]')
        sys.exit(1)

    password = args[0]
    email = args[1] if "--email" in sys.argv and len(args) > 1 else None

    # bcrypt trunca a 72 bytes; avisar si se supera
    if len(password.encode("utf-8")) > 72:
        print("AVISO: la contraseña supera 72 bytes; bcrypt la truncará.", file=sys.stderr)

    hashed = bcrypt.hash(str(password))
    print(hashed)

    if email:
        print()
        print("-- UPDATE SQL (ejecutar en la base de datos correcta):")
        print(
            f"UPDATE Users SET Password = '{hashed}', UpdatedAt = GETDATE() "
            f"WHERE Email = '{email}';"
        )


if __name__ == "__main__":
    main()
