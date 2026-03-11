```json
{
  "contract_review": [
    {
      "id": "component_stats_payload",
      "status": "covered",
      "plan": "Implement aggregation of componentStats.languages, statusCounts, and maxPoints in the service for the problem detail response."
    },
    {
      "id": "error_handling",
      "status": "covered",
      "plan": "Return HTTP 404 with JSON error body when problemId does not exist, implemented in service and controller."
    },
    {
      "id": "architecture",
      "status": "covered",
      "plan": "Keep controller thin by delegating aggregation and error handling to the service without controller-side filtering or mutation."
    }
  ],
  "edits": [
    {
      "path": "modules/Problems/services/ProblemsService.js",
      "mode": "rewrite",
      "content": "'use strict';\n\n/*\n * Copyright (c) 2016 TopCoder, Inc.\n */\n\n/**\n * Service for SRM problem APIs.\n */\nconst fs = require('fs');\nconst path = require('path');\nconst Joi = require('joi');\nconst logger = require('../../../common/logger');\n\nlet cachedProblems;\n\nconst MAX_LIMIT = 50;\n\n/**\n * Normalize tags filter into a lowercase array.\n * @param {string|Array<string>} rawTags\n * @returns {Array<string>}\n */\nfunction normalizeTags(rawTags) {\n  if (!rawTags && rawTags !== '') {\n    return [];\n  }\n  const list = Array.isArray(rawTags) ? rawTags : String(rawTags).split(',');\n  return list\n    .map((tag) => String(tag || '').trim().toLowerCase())\n    .filter((tag) => tag);\n}\n\n/**\n * Check whether the problem contains at least one of the requested tags.\n * @param {Object} problem\n * @param {Array<string>} tags\n * @returns {boolean}\n */\nfunction problemHasTags(problem, tags) {\n  if (!tags || tags.length === 0) {\n    return true;\n  }\n  if (!problem.tags || !Array.isArray(problem.tags)) {\n    return false;\n  }\n  const problemTags = problem.tags.map((t) => t.toLowerCase());\n  return tags.some((tag) => problemTags.includes(tag));\n}\n\n/**\n * Load problems from data file.\n * @returns {Array<Object>}\n */\nfunction loadProblems() {\n  if (cachedProblems) {\n    return cachedProblems;\n  }\n  const dataPath = path.resolve(__dirname, '../../data/problems.json');\n  const raw = fs.readFileSync(dataPath, 'utf8');\n  cachedProblems = JSON.parse(raw);\n  return cachedProblems;\n}\n\n/**\n * List problems with optional filtering.\n * @param {Object} query\n * @returns {Promise<Object>} payload\n */\nfunction* listProblems(query) {\n  const problems = loadProblems();\n  const tags = normalizeTags(query.tags);\n\n  let filtered = problems.filter((p) => problemHasTags(p, tags));\n\n  // Apply limit\n  let limit = parseInt(query.limit, 10);\n  if (isNaN(limit) || limit < 1) {\n    limit = MAX_LIMIT;\n  } else if (limit > MAX_LIMIT) {\n