```json
{
  "contract_review": [
    {
      "id": "filtering",
      "status": "covered",
      "plan": "Implement filtering by difficulty case-insensitively, enforce 50-result limit, and report metadata fields totalProblems, filteredCount, appliedLimit, difficultyBreakdown in the service."
    },
    {
      "id": "sorting",
      "status": "covered",
      "plan": "Sort returned problems deterministically by roundId ascending within the filtered set, and sort per-problem componentLanguages case-insensitively and deduplicated."
    },
    {
      "id": "aggregation",
      "status": "covered",
      "plan": "When includeComponents=true, compute metadata.componentLanguageTotals and componentStatusTotals from the filtered+limited set, and include per-problem componentLanguages arrays reflecting the filtered+limited set."
    },
    {
      "id": "sorting",
      "status": "covered",
      "plan": "Ensure per-problem componentLanguages arrays are deduplicated and sorted case-insensitively."
    }
  ],
  "edits": [
    {
      "path": "modules/Problems/services/ProblemsService.js",
      "mode": "rewrite",
      "content": "'use strict';\n\n/*\n * Copyright (c) 2016 TopCoder, Inc.\n */\n\n/**\n * Service for SRM problem APIs.\n */\nconst fs = require('fs');\nconst path = require('path');\nconst Joi = require('joi');\nconst logger = require('../../../common/logger');\n\nlet cachedProblems;\n\nconst MAX_LIMIT = 50;\n\n/**\n * Normalize tags filter into a lowercase array.\n * @param {string|Array<string>} rawTags\n * @returns {Array<string>}\n */\nfunction normalizeTags(rawTags) {\n  if (!rawTags && rawTags !== '') {\n    return [];\n  }\n  const list = Array.isArray(rawTags) ? rawTags : String(rawTags).split(',');\n  return list\n    .map((tag) => String(tag || '').trim().toLowerCase())\n    .filter((tag) => tag);\n}\n\n/**\n * Check whether the problem contains at least one of the requested tags.\n * @param {Object} problem\n * @param {Array<string>} tags\n * @returns {boolean}\n */\nfunction problemHasTags(problem, tags) {\n  if (!tags || tags.length === 0) {\n    return true;\n  }\n  if (!problem.tags || !Array.isArray(problem.tags)) {\n    return false;\n  }\n  const problemTags = problem.tags.map((t) => t.toLowerCase());\n  return tags.some((tag) => problemTags.includes(tag));\n}\n\n/**\n * Load problems from JSON file and cache them.\n * @returns {Array<Object>} problems\n */\nfunction loadProblems() {\n  if (cachedProblems) {\n    return cachedProblems;\n  }\n  const filePath = path.join(__dirname, '../../data/problems.json');\n  const raw = fs.readFileSync(filePath, 'utf8');\n  cachedProblems = JSON.parse(raw);\n  return cachedProblems;\n}\n\n/**\n * Deduplicate and case-insensitively sort an array of strings.\n * @param {Array<string>} arr\n * @returns {Array<string>}\n */\nfunction dedupeAndSortCaseInsensitive(arr) {\