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
    "CreatedAt" TEXT DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    "UpdatedAt" TEXT DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
    "IsNew" INTEGER DEFAULT 1,
    "PostedDate" TEXT,
    "ExpiryDate" TEXT,
    "IsActive" INTEGER DEFAULT 1,
    "JobDescription" TEXT,
    "TechStack" TEXT
);

CREATE INDEX IF NOT EXISTS idx_seek_jobs_region
    ON "seek_jobs" ("Region");

CREATE INDEX IF NOT EXISTS idx_seek_jobs_posteddate
    ON "seek_jobs" ("PostedDate");

CREATE INDEX IF NOT EXISTS idx_seek_jobs_isactive
    ON "seek_jobs" ("IsActive");

CREATE INDEX IF NOT EXISTS idx_seek_jobs_updatedat
    ON "seek_jobs" ("UpdatedAt");
