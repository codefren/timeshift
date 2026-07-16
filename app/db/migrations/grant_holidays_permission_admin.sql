-- ============================================================================
-- Grant: asignar el permiso manage:Holidays a los roles admin
-- ----------------------------------------------------------------------------
-- Concede 'manage:Holidays' a TODOS los roles cuyo nombre sea 'admin'
-- (resuelto por RoleName, no por RoleID, para que sea válido también en
-- producción donde el ID puede diferir).
--
-- Requiere que el permiso ya exista (ver seed_holidays_permission.sql). Si no
-- existe, este script no hace nada (y avisa).
--
-- Idempotente. Motor: SQL Server (T-SQL). Base de datos: ShiftZone.
-- ============================================================================

SET NOCOUNT ON;

DECLARE @pid INT = (SELECT PermissionID FROM Permissions WHERE PermissionName = 'manage:Holidays');

IF @pid IS NULL
BEGIN
    RAISERROR('El permiso manage:Holidays no existe. Ejecuta antes seed_holidays_permission.sql', 16, 1);
END
ELSE
BEGIN
    INSERT INTO RolePermissions (RoleID, PermissionID)
    SELECT r.RoleID, @pid
    FROM Roles r
    WHERE r.RoleName = 'admin'
      AND NOT EXISTS (
          SELECT 1 FROM RolePermissions rp
          WHERE rp.RoleID = r.RoleID AND rp.PermissionID = @pid
      );

    PRINT CONCAT('manage:Holidays asignado a ', @@ROWCOUNT, ' rol(es) admin.');
END
GO
