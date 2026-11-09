-- =============================================================
--  Seed de permisos de la integración Ausencias / Festivos
--  Crea los permisos y los vincula a los roles admin y employee.
--  Idempotente: puede ejecutarse varias veces sin duplicar.
--  Ajusta el nombre de la base en el USE si difiere.
-- =============================================================
USE [timeshift];
GO

SET NOCOUNT ON;

-- ── 1. Crear permisos (solo si no existen) ───────────────────
INSERT INTO dbo.Permissions (PermissionName, Description, ForFrontend)
SELECT v.PermissionName, v.Description, v.ForFrontend
FROM (VALUES
    ('manage:Absences', 'Aprobar/rechazar ausencias y saldos', CAST(1 AS BIT)),
    ('view:Absences',   'Ver solicitudes de ausencias',        CAST(0 AS BIT)),
    ('manage:Holidays', 'Gestionar festivos',                  CAST(1 AS BIT))
) AS v(PermissionName, Description, ForFrontend)
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.Permissions p WHERE p.PermissionName = v.PermissionName
);

-- ── 2. Menús de frontend (para permisos con ForFrontend=1) ───
INSERT INTO dbo.PermissionMenus (PermissionID, Menu)
SELECT p.PermissionID, v.Menu
FROM (VALUES
    ('manage:Absences', 'manage_absences'),
    ('manage:Holidays', 'manage_holidays')
) AS v(PermissionName, Menu)
JOIN dbo.Permissions p ON p.PermissionName = v.PermissionName
WHERE NOT EXISTS (
    SELECT 1 FROM dbo.PermissionMenus pm
    WHERE pm.PermissionID = p.PermissionID AND pm.Menu = v.Menu
);

-- ── 3. Asignar al rol ADMIN los 3 permisos ───────────────────
INSERT INTO dbo.RolePermissions (RoleID, PermissionID)
SELECT r.RoleID, p.PermissionID
FROM dbo.Roles r
JOIN dbo.Permissions p
     ON p.PermissionName IN ('manage:Absences', 'view:Absences', 'manage:Holidays')
WHERE r.RoleName = 'admin'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.RolePermissions rp
      WHERE rp.RoleID = r.RoleID AND rp.PermissionID = p.PermissionID
  );

-- ── 4. Asignar al rol EMPLOYEE solo view:Absences ────────────
INSERT INTO dbo.RolePermissions (RoleID, PermissionID)
SELECT r.RoleID, p.PermissionID
FROM dbo.Roles r
JOIN dbo.Permissions p ON p.PermissionName = 'view:Absences'
WHERE r.RoleName = 'employee'
  AND NOT EXISTS (
      SELECT 1 FROM dbo.RolePermissions rp
      WHERE rp.RoleID = r.RoleID AND rp.PermissionID = p.PermissionID
  );
GO

-- ── 5. Verificación ──────────────────────────────────────────
SELECT r.RoleName, p.PermissionName, p.ForFrontend, pm.Menu
FROM dbo.RolePermissions rp
JOIN dbo.Roles r       ON r.RoleID = rp.RoleID
JOIN dbo.Permissions p ON p.PermissionID = rp.PermissionID
LEFT JOIN dbo.PermissionMenus pm ON pm.PermissionID = p.PermissionID
WHERE p.PermissionName IN ('manage:Absences', 'view:Absences', 'manage:Holidays')
ORDER BY r.RoleName, p.PermissionName;
GO
