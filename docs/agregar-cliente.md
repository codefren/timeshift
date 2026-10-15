# Manual — Agregar un nuevo cliente (backend)

Cada cliente es una instancia independiente: **su propio backend, su propia base
de datos y su propio dominio**. No se comparten datos entre clientes; Caddy
enruta cada dominio directo a su backend.

Hoy hay 3 clientes:

| Cliente | Servicio (compose) | Contenedor | Base | Dominio |
|---|---|---|---|---|
| bycos | `backend-1` | `tsz-bycosshiftzone` | `timeshift_1` | `bycosshiftzone.store4tex.com` |
| dressing | `backend-2` | `tsz-dressingshiftzone` | `timeshift_2` | `dressingshiftzone.store4tex.com` |
| tv | `backend-3` | `tsz-tvshiftzone` | `timeshift_3` | `tvshiftzone.store4tex.com` |

> El **frontend NO hay que tocarlo**: los 3 (y los futuros) backends sirven el
> mismo `app/static` con llamadas relativas a `/api`, así que vale para cualquier
> dominio. No se recompila ni se despliega nada del frontend al añadir un cliente.

Supongamos que el nuevo cliente es **`newclient`**, con dominio
`newclientshiftzone.store4tex.com` → será `backend-4` / `timeshift_4`.

---

## 1. DNS

Crea el registro A del nuevo dominio apuntando a la IP del VPS. Ver el manual
[dns.md](dns.md). Espera a que resuelva antes de recargar Caddy (si no, Let's
Encrypt no podrá emitir el certificado).

## 2. `.env.cluster` (en el VPS)

Añade las variables del nuevo cliente:

```bash
# ── Cliente 4: newclient ──
DB_NAME_4=timeshift_4
BAK_FILE_4=timeshift_4.bak
DOMAIN_4=newclientshiftzone.store4tex.com
DOMAIN_4_URL=https://newclientshiftzone.store4tex.com
```

- `BAK_FILE_4`: si dejas el `.bak` del cliente en `backups/`, la base se
  **restaura** desde ahí. Si no existe el fichero, se **crea vacía** con el
  esquema de la app (`init_databases.py` lo decide solo).

## 3. `docker-compose.cluster.yml` — nuevo backend

Copia el bloque de `backend-3` y cámbialo. El `container_name` sigue la
convención **`tsz-<subdominio>`** para identificarlo en `docker ps`:

```yaml
  # ── Backend 4 → timeshift_4 ────────────────────────────────────────────────
  backend-4:
    <<: *backend
    container_name: tsz-newclientshiftzone
    environment:
      <<: *backend-env
      INSTANCE_ID: backend-4
      DB_NAME: "${DB_NAME_4:-timeshift_4}"
      FRONTEND_URL: "${DOMAIN_4_URL:-https://newclientshiftzone.store4tex.com}"
    volumes:
      - ./app:/code/app
      - ./docker/logs/backend-4:/code/app/logs
      - profile-pictures-4:/code/app/static/images
```

Y declara su volumen de fotos al final, junto a los demás:

```yaml
volumes:
  sqlserver-data:
  profile-pictures-1:
  profile-pictures-2:
  profile-pictures-3:
  profile-pictures-4:   # ← nuevo
  caddy-data:
  caddy-config:
```

(Opcional) añade `backend-4` al `depends_on` del servicio `caddy`, para que
Caddy espere a que exista antes de arrancar.

## 4. `docker/Caddyfile` — nuevo dominio

Añade un bloque de sitio al final, reutilizando el snippet `frontend`:

```caddy
{$DOMAIN_4:newclientshiftzone.store4tex.com} {
	import frontend backend-4:8000
}
```

> Ojo: `import frontend backend-4:8000` usa el **nombre de servicio**
> (`backend-4`), no el `container_name`. Ver [la sección de nombres](#6-nombres-de-contenedor-por-dns).

Y en `docker-compose.cluster.yml`, pásale la variable a Caddy (servicio `caddy`,
bloque `environment`):

```yaml
      DOMAIN_4: "${DOMAIN_4:-newclientshiftzone.store4tex.com}"
```

## 5. Levantar y verificar

```bash
cd /home/sms4tex/timeshift
docker compose -f docker-compose.cluster.yml --env-file .env.cluster up -d --build
```

Esto crea `backend-4`, y `db-init` detecta automáticamente `DB_NAME_4` y
crea/restaura `timeshift_4` (el script ya es dinámico, no hay que tocar Python).

Recarga Caddy para el nuevo dominio + certificado (sin downtime):

```bash
docker exec tsz-caddy caddy validate --config /etc/caddy/Caddyfile
docker exec tsz-caddy caddy reload   --config /etc/caddy/Caddyfile
docker logs -f tsz-caddy   # ver la emisión del certificado
```

Comprobaciones:

```bash
docker compose -f docker-compose.cluster.yml --env-file .env.cluster ps
curl -I https://newclientshiftzone.store4tex.com
```

El backend debe salir `Up (healthy)` y el `curl` devolver `HTTP/2 200`.

## 6. Nombres de contenedor por DNS

Hay **dos nombres** distintos para cada backend y conviene no confundirlos:

- **Nombre de servicio** (`backend-4`): es el **DNS interno** de la red Docker.
  Es el que usan Caddy (`reverse_proxy backend-4:8000`) y `depends_on`.
  **No lo cambies** salvo que actualices también esas referencias.
- **`container_name`** (`tsz-newclientshiftzone`): es solo la **etiqueta visible**
  en `docker ps`, `docker logs`, `docker exec`. Cambiarlo no afecta al enrutado.

Convención adoptada: `container_name: tsz-<subdominio-completo>`, para que un
`docker ps` identifique cada contenedor por su cliente/dominio:

```
tsz-bycosshiftzone      bycosshiftzone.store4tex.com
tsz-dressingshiftzone   dressingshiftzone.store4tex.com
tsz-tvshiftzone         tvshiftzone.store4tex.com
```

Así los comandos quedan legibles:

```bash
docker logs -f tsz-newclientshiftzone
docker exec -it tsz-newclientshiftzone bash
```

> Cambiar un `container_name` recrea ese contenedor en el siguiente
> `up -d` (unos segundos de corte solo para ese backend). Los datos no se pierden:
> la base vive en el volumen `sqlserver-data` y las fotos en `profile-pictures-N`.

## 7. Perfiles opcionales (solo si los usas)

Los servicios `seeder` y `make-test-backups` (perfiles `seed` / `testdata`)
todavía listan `DB_NAME_1/2/3` de forma fija en su script. Si usas esos perfiles
con el nuevo cliente, añade `$$DB_NAME_4` a sus bucles en
`docker-compose.cluster.yml`. Para el funcionamiento normal **no hace falta**.

---

## Checklist rápido

- [ ] Registro DNS A del nuevo dominio → IP del VPS ([dns.md](dns.md))
- [ ] `.env.cluster`: `DB_NAME_4`, `BAK_FILE_4`, `DOMAIN_4`, `DOMAIN_4_URL`
- [ ] (opcional) `.bak` del cliente en `backups/`
- [ ] `docker-compose.cluster.yml`: servicio `backend-4` + volumen `profile-pictures-4` + `DOMAIN_4` en `caddy`
- [ ] `docker/Caddyfile`: bloque del nuevo dominio
- [ ] `up -d --build` + `caddy reload`
- [ ] `curl -I https://<dominio>` → 200
