-- Initial schema for Topcoder DataCollector

CREATE TABLE IF NOT EXISTS {challenges_table} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    challengeId VARCHAR(50) NOT NULL,
    legacyId INT,
    directProjectId INT,
    status MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
    trackType VARCHAR(20),
    type VARCHAR(20),
    name VARCHAR(512),
    description MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
    totalPrizeCost INT,
    winners MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
    registrationStartDate DATETIME,
    registrationEndDate DATETIME,
    submissionStartDate DATETIME,
    submissionEndDate DATETIME,
    startDate DATETIME,
    endDate DATETIME,
    technologies VARCHAR(512),
    numOfSubmissions INT,
    numOfRegistrants INT,
    forumId INT,
    UNIQUE KEY uq_challenge_id (challengeId)
);

CREATE TABLE IF NOT EXISTS {challenge_member_mapping_table} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    challengeId VARCHAR(50) NOT NULL,
    legacyId INT,
    memberHandle VARCHAR(50) NOT NULL,
    submission BOOL,
    winningPosition INT,
    UNIQUE KEY uq_challenge_member (challengeId, memberHandle)
);

CREATE TABLE IF NOT EXISTS {members_table} (
    userId INT,
    memberHandle VARCHAR(512) PRIMARY KEY,
    DEVELOP BOOL,
    DESIGN BOOL,
    DATA_SCIENCE BOOL,
    maxRating INT,
    track VARCHAR(512),
    subTrack VARCHAR(512),
    registrations INT,
    wins INT,
    user_entered MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
    participation_skill MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
    updatedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
