-- =============================================================
--  Crear un usuario ADMIN y un EMPLOYEE directamente en la DB
--  Password: bcrypt (passlib) — NO se puede generar en SQL puro,
--  los hashes se calcularon con passlib.hash.bcrypt (igual que el backend).
--
--    admin@timeshift.local     ->  Admin123!
--    employee@timeshift.local  ->  Employee123!
--
--  Idempotente: no duplica si los emails ya existen.
-- =============================================================
USE [timeshift];
GO
SET NOCOUNT ON;
SET XACT_ABORT ON;
BEGIN TRAN;

DECLARE @now      DATETIME = GETDATE();
DECLARE @adminId  INT;
DECLARE @empId    INT;

-- ── 1. ADMIN ─────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM dbo.Users WHERE Email = 'admin@timeshift.local')
BEGIN
    INSERT INTO dbo.Users (Email, Password, IsInactive, CreatedAt, UpdatedAt)
    VALUES ('admin@timeshift.local',
            '$2b$12$G.72jImt5aU8yGbAAhrxd.ntE7.qwui/WuY4Idhh7H2ExDx8ppiIq',  -- Admin123!
            0, @now, @now);
    SET @adminId = SCOPE_IDENTITY();

    INSERT INTO dbo.UserDetail
        (UserID, FirstName, LastName1, LastName2, Gender, PhoneNumber, PersonalEmail,
         IdentityNumber, Nationality, SSNumber, DateOfBirth, HireDate, JobTitle,
         ContractType, ContractWeeklyHours)
    VALUES
        (@adminId, 'Admin', 'TimeShift', '', 'M', '000000000', 'admin@timeshift.local',
         '00000000A', 'ES', '000000000000', '19900101', '20250101', 'Administrator',
         'Indefinido', 40.0);
END
ELSE
    SET @adminId = (SELECT UserID FROM dbo.Users WHERE Email = 'admin@timeshift.local');

-- Vincular al rol admin (por nombre, idempotente)
INSERT INTO dbo.RoleUsers (RoleID, UserID)
SELECT r.RoleID, @adminId
FROM dbo.Roles r
WHERE r.RoleName = 'admin'
  AND NOT EXISTS (SELECT 1 FROM dbo.RoleUsers ru WHERE ru.RoleID = r.RoleID AND ru.UserID = @adminId);

-- ── 2. EMPLOYEE ──────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM dbo.Users WHERE Email = 'employee@timeshift.local')
BEGIN
    INSERT INTO dbo.Users (Email, Password, IsInactive, CreatedAt, UpdatedAt)
    VALUES ('employee@timeshift.local',
            '$2b$12$j.hwWS3neyiZ1otD8qKEX.TvxBLHwLD9bzqWc.5sIeH.kIEnGTY.q',  -- Employee123!
            0, @now, @now);
    SET @empId = SCOPE_IDENTITY();

    INSERT INTO dbo.UserDetail
        (UserID, FirstName, LastName1, LastName2, Gender, PhoneNumber, PersonalEmail,
         IdentityNumber, Nationality, SSNumber, DateOfBirth, HireDate, JobTitle,
         ContractType, ContractWeeklyHours)
    VALUES
        (@empId, 'Empleado', 'Demo', '', 'M', '111111111', 'employee@timeshift.local',
         '11111111B', 'ES', '111111111111', '19950515', '20250101', 'Operario',
         'Indefinido', 40.0);
END
ELSE
    SET @empId = (SELECT UserID FROM dbo.Users WHERE Email = 'employee@timeshift.local');

-- Vincular al rol employee (por nombre, idempotente)
INSERT INTO dbo.RoleUsers (RoleID, UserID)
SELECT r.RoleID, @empId
FROM dbo.Roles r
WHERE r.RoleName = 'employee'
  AND NOT EXISTS (SELECT 1 FROM dbo.RoleUsers ru WHERE ru.RoleID = r.RoleID AND ru.UserID = @empId);

COMMIT TRAN;
GO

-- ── Verificación ─────────────────────────────────────────────
SELECT u.UserID, u.Email, r.RoleName, ud.FirstName, ud.LastName1
FROM dbo.Users u
JOIN dbo.RoleUsers ru ON ru.UserID = u.UserID
JOIN dbo.Roles r      ON r.RoleID  = ru.RoleID
LEFT JOIN dbo.UserDetail ud ON ud.UserID = u.UserID
WHERE u.Email IN ('admin@timeshift.local', 'employee@timeshift.local');
GO
