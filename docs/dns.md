# Manual — Crear un nuevo DNS (subdominio) para un cliente

Cada cliente se sirve en un **subdominio** de `store4tex.com` que apunta a la IP
del VPS. Todos los subdominios usan la **misma IP**: Caddy decide a qué backend
va cada petición según el dominio.

- **IP del VPS:** `82.223.234.89`
- **Dominio raíz:** `store4tex.com`
- **DNS gestionado en:** Arsys (nameservers `dns*.servidoresdns.net`)

Subdominios actuales:

| Subdominio | Apunta a |
|---|---|
| `bycosshiftzone.store4tex.com` | 82.223.234.89 |
| `dressingshiftzone.store4tex.com` | 82.223.234.89 |
| `tvshiftzone.store4tex.com` | 82.223.234.89 |

---

## 1. Confirmar dónde se gestiona el DNS

```bash
nslookup -type=NS store4tex.com 8.8.8.8
```

Si devuelve `dns*.servidoresdns.net`, el DNS está en **Arsys**: panel de Arsys →
Dominios → `store4tex.com` → **Gestión DNS / Zona DNS**.

## 2. Crear el registro A

En la zona DNS, añade un registro:

| Campo | Valor |
|---|---|
| **Tipo** | `A` |
| **Nombre / Host** | el subdominio, p. ej. `newclientshiftzone` |
| **Valor / Destino** | `82.223.234.89` (IP del VPS) |
| **TTL** | `3600` (o 300 si quieres que propague rápido) |

Notas importantes:

- En **Nombre** se pone **solo la etiqueta** (`newclientshiftzone`), no el dominio
  completo. El panel añade `.store4tex.com` por su cuenta.
- **No crees un registro `AAAA`** salvo que el VPS tenga IPv6 configurado. Si
  existe un `AAAA` antiguo apuntando a otro sitio, bórralo: Let's Encrypt prueba
  primero por IPv6 y fallaría la emisión del certificado.
- Si algún día el DNS pasara por **Cloudflare**, deja la nube en **gris**
  (solo DNS) para que Caddy pueda validar el certificado sin intermediarios.

## 3. Comprobar que propaga

```bash
nslookup newclientshiftzone.store4tex.com 8.8.8.8
```

Debe devolver `82.223.234.89`. Suele tardar unos minutos (hasta 1 h como
máximo). **No recargues Caddy hasta que resuelva**, o la emisión del certificado
fallará y Let's Encrypt aplica límites temporales.

## 4. Puertos / firewall

No hay que tocar nada: los puertos **80 y 443 ya están abiertos** en el firewall
de Arsys y Caddy ya escucha en ellos. El 80 **debe** seguir abierto porque
Let's Encrypt lo usa para validar el dominio.

## 5. Siguiente paso

Con el DNS resolviendo, continúa en el manual
[agregar-cliente.md](agregar-cliente.md) para crear el backend y el bloque de
Caddy del nuevo dominio.

---

## Resumen

1. `A  <subdominio>  →  82.223.234.89`  (TTL 3600, sin `AAAA`)
2. `nslookup <subdominio>.store4tex.com 8.8.8.8` → debe dar la IP
3. Luego: crear el backend y recargar Caddy ([agregar-cliente.md](agregar-cliente.md))
