```json
{
  "contract_review": [
    {
      "id": "filtering",
      "status": "covered",
      "plan": "Normalize tags case-insensitively, support comma-separated and array forms, filter problems by any matching tag, expose normalized tags in metadata.appliedTags, and preserve ordering and paging with difficulty filters."
    },
    {
      "id": "multi_tag_union",
      "status": "covered",
      "plan": "Parse comma-separated tags, normalize to lowercase, filter problems that contain any of these tags, and expose all normalized tags in metadata.appliedTags."
    },
    {
      "id": "array_tag_filter",
      "status": "covered",
      "plan": "Support tags[]=... array form alongside difficulty filters, normalize tags, filter problems by any matching tag, and preserve ordering by roundId and paging limit."
    }
  ],
  "edits": [
    {
      "path": "modules/Problems/services/ProblemsService.js",
      "mode": "rewrite",
      "content": "'use strict';\n\n/*\n * Copyright (c) 2016 TopCoder, Inc.\n */\n\n/**\n * Service for SRM problem APIs.\n */\nconst fs = require('fs');\nconst path = require('path');\nconst Joi = require('joi');\nconst logger = require('../../../common/logger');\n\nlet cachedProblems;\n\nconst MAX_LIMIT = 50;\n\n/**\n * Normalize tags filter into a lowercase array.\n * @param {string|Array<string>} rawTags\n * @returns {Array<string>}\n */\nfunction normalizeTags(rawTags) {\n  if (!rawTags && rawTags !== '') {\n    return [];\n  }\n  const list = Array.isArray(rawTags) ? rawTags : String(rawTags).split(',');\n  return list\n    .map((tag) => String(tag || '').trim().toLowerCase())\n    .filter((tag) => tag);\n}\n\n/**\n * Check whether the problem contains at least one of the requested tags.\n * @param {Object} problem\n * @param {Array<string>} tags\n * @returns {boolean}\n */\nfunction problemHasAnyTag(problem, tags) {\n  if (!tags || tags.length === 0) {\n    return true;\n  }\n  if (!problem.metadata || !problem.metadata.appliedTags) {\n    return false;\n  }\n  const problemTags = problem.metadata.appliedTags.map((t) => t.toLowerCase());\n  return tags.some((tag) => problemTags.includes(tag));\n}\n\n/**\n * Load problems from JSON file and cache them.\n * @returns {Array<Object>}\n */\nfunction loadProblems() {\n  if (cachedProblems) {\n    return cachedProblems;\n  }\n  const filePath = path.join(__dirname, '../../data/problems.json');\n  const raw = fs.readFileSync(filePath, 'utf8');\n  cachedProblems = JSON.parse(raw);\n  return cachedProblems;\n}\n\n/**\n * List problems with optional filtering and pagination.\n * @param {Object} query\n * @param {string|string[]} [query.tags] - tags filter, comma-separated string or array\n * @param {string|string[]} [query['tags[]']] - alternative array form for tags\n * @param {string} [query.difficulty] - difficulty filter\n * @param {number} [query.limit] -