-- ============================================================================
-- Seed: permiso manage:Holidays (gestión de festivos)
-- ----------------------------------------------------------------------------
-- El permiso 'manage:Holidays' y su menú 'manage_holidays' están definidos en
-- app/db/create_first_data.py (ADMIN_PERMISSIONS) pero no se sembraron en bases
-- restauradas desde un backup anterior a la feature de festivos. Sin él, nadie
-- puede crear/editar/eliminar festivos (403) ni ve el botón en el frontend.
--
-- Este script crea el permiso, lo mapea al menú y lo concede al rol admin.
-- Idempotente. Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- ============================================================================

SET NOCOUNT ON;

IF NOT EXISTS (SELECT 1 FROM Permissions WHERE PermissionName = 'manage:Holidays')
    INSERT INTO Permissions (PermissionName, Description, ForFrontend)
    VALUES ('manage:Holidays', 'Gestionar festivos', 1);

DECLARE @pid INT = (SELECT PermissionID FROM Permissions WHERE PermissionName = 'manage:Holidays');

IF NOT EXISTS (SELECT 1 FROM PermissionMenus WHERE PermissionID = @pid AND Menu = 'manage_holidays')
    INSERT INTO PermissionMenus (PermissionID, Menu) VALUES (@pid, 'manage_holidays');

-- Conceder al rol admin (RoleID = 1)
IF NOT EXISTS (SELECT 1 FROM RolePermissions WHERE RoleID = 1 AND PermissionID = @pid)
    INSERT INTO RolePermissions (RoleID, PermissionID) VALUES (1, @pid);
GO
