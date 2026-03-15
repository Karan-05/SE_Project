```json
{
  "contract_review": [
    {
      "id": "single_tag_filter",
      "status": "covered",
      "notes": "Implemented normalizeTags to lowercase and handle single tag string; filtering matches any problem with at least one tag in the normalized list; metadata.appliedTags returns normalized tags."
    },
    {
      "id": "multi_tag_union",
      "status": "covered",
      "notes": "Comma-separated tags are split, normalized to lowercase, and used as a union filter; problems matching any tag are included; metadata.appliedTags includes all normalized tags."
    },
    {
      "id": "array_tag_filter",
      "status": "covered",
      "notes": "tags[] array form is normalized and combined with difficulty filters; filtering preserves ordering by roundId ascending and limits results to 50; metadata.appliedTags reflects normalized tags."
    }
  ],
  "edits": [
    {
      "path": "modules/Problems/services/ProblemsService.js",
      "mode": "rewrite",
      "content": "'use strict';\n\n/*\n * Copyright (c) 2016 TopCoder, Inc.\n */\n\n/**\n * Service for SRM problem APIs.\n */\nconst fs = require('fs');\nconst path = require('path');\nconst Joi = require('joi');\nconst logger = require('../../../common/logger');\n\nlet cachedProblems;\n\nconst MAX_LIMIT = 50;\n\n/**\n * Normalize tags filter into a lowercase array.\n * @param {string|Array<string>} rawTags\n * @returns {Array<string>}\n */\nfunction normalizeTags(rawTags) {\n  if (rawTags === undefined || rawTags === null) {\n    return [];\n  }\n  if (Array.isArray(rawTags)) {\n    return rawTags\n      .map((tag) => String(tag || '').trim().toLowerCase())\n      .filter((tag) => tag);\n  }\n  // rawTags is string\n  return String(rawTags)\n    .split(',')\n    .map((tag) => tag.trim().toLowerCase())\n    .filter((tag) => tag);\n}\n\n/**\n * Check whether the problem contains at least one of the requested tags.\n * @param {Object} problem\n * @param {Array<string>} requestedTags\n * @returns {boolean}\n */\nfunction problemMatchesTags(problem, requestedTags) {\n  if (!requestedTags || requestedTags.length === 0) {\n    return true;\n  }\n  if (!problem.metadata || !Array.isArray(problem.metadata.appliedTags)) {\n    return false;\n  }\n  const problemTags = problem.metadata.appliedTags.map((t) => t.toLowerCase());\n  return requestedTags.some((tag) => problemTags.includes(tag));\n}\n\n/**\n * Load problems from JSON file and cache them.\n * @returns {Array<Object>}\n */\nfunction loadProblems() {\n  if (cachedProblems) {\n    return cachedProblems;\n  }\n  const filePath = path.join(__dirname, '..', '..', '..', 'data', 'problems.json');\n  const raw = fs.readFileSync(filePath, 'utf8');\n  cachedProblems = JSON.parse(raw);\n  return cachedProblems;\n}\n\n/**\n * List problems with optional filtering by tags and difficulty.\n * Supports ?tags=foo,bar or tags[]=foo&