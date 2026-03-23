CREATE TABLE IF NOT EXISTS "seek_jobs" (
    "Id" TEXT PRIMARY KEY,
    "JobTitle" TEXT,
    "BusinessName" TEXT,
    "WorkType" TEXT,
    "PayRange" TEXT,
    "Suburb" TEXT,
    "Area" TEXT,
    "Region" TEXT,
    "Url" TEXT,
    "AdvertiserId" TEXT,
    "JobType" TEXT,
    "CreatedAt" TIMESTAMPTZ DEFAULT NOW(),
    "UpdatedAt" TIMESTAMPTZ DEFAULT NOW(),
    "IsNew" BOOLEAN DEFAULT TRUE,
    "PostedDate" TIMESTAMPTZ,
    "ExpiryDate" TIMESTAMPTZ,
    "IsActive" BOOLEAN DEFAULT TRUE,
    "JobDescription" TEXT,
    "TechStack" JSONB
);

CREATE INDEX IF NOT EXISTS idx_seek_jobs_region
    ON "seek_jobs" ("Region");

CREATE INDEX IF NOT EXISTS idx_seek_jobs_posteddate
    ON "seek_jobs" ("PostedDate");

CREATE INDEX IF NOT EXISTS idx_seek_jobs_isactive
    ON "seek_jobs" ("IsActive");

CREATE INDEX IF NOT EXISTS idx_seek_jobs_updatedat
    ON "seek_jobs" ("UpdatedAt");