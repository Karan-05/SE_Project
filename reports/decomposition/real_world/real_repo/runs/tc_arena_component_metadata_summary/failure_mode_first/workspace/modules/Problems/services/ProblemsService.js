```json
{
  "contract_review": [
    {
      "id": "aggregation",
      "status": "covered",
      "plan": "Filter and limit problems first, then aggregate componentLanguageTotals and componentStatusTotals only from the filtered and limited problems. Deduplicate and sort componentLanguages per problem case-insensitively."
    },
    {
      "id": "limit",
      "status": "covered",
      "plan": "Apply the limit before aggregations so only the returned problems influence metadata totals."
    },
    {
      "id": "sorting",
      "status": "covered",
      "plan": "Deduplicate and sort componentLanguages arrays case-insensitively per problem."
    }
  ],
  "edits": [
    {
      "path": "modules/Problems/services/ProblemsService.js",
      "mode": "rewrite",
      "content": "'use strict';\n\n/*\n * Copyright (c) 2016 TopCoder, Inc.\n */\n\n/**\n * Service for SRM problem APIs.\n */\nconst fs = require('fs');\nconst path = require('path');\nconst Joi = require('joi');\nconst logger = require('../../../common/logger');\n\nlet cachedProblems;\n\nconst MAX_LIMIT = 50;\n\n/**\n * Normalize tags filter into a lowercase array.\n * @param {string|Array<string>} rawTags\n * @returns {Array<string>}\n */\nfunction normalizeTags(rawTags) {\n  if (!rawTags && rawTags !== '') {\n    return [];\n  }\n  const list = Array.isArray(rawTags) ? rawTags : String(rawTags).split(',');\n  return list\n    .map((tag) => String(tag || '').trim().toLowerCase())\n    .filter((tag) => tag);\n}\n\n/**\n * Check whether the problem contains at least one of the requested tags.\n * @param {Object} problem\n * @param {Array<string>} tags\n * @returns {boolean}\n */\nfunction problemHasTags(problem, tags) {\n  if (!tags || tags.length === 0) {\n    return true;\n  }\n  if (!problem.tags || !Array.isArray(problem.tags)) {\n    return false;\n  }\n  const problemTags = problem.tags.map((t) => t.toLowerCase());\n  return tags.some((tag) => problemTags.includes(tag));\n}\n\n/**\n * Load problems from JSON file and cache them.\n * @returns {Array<Object>}\n */\nfunction loadProblems() {\n  if (cachedProblems) {\n    return cachedProblems;\n  }\n  const filePath = path.resolve(__dirname, '../../data/problems.json');\n  const raw = fs.readFileSync(filePath, 'utf8');\n  cachedProblems = JSON.parse(raw);\n  return cachedProblems;\n}\n\n/**\n * List problems with optional filters and metadata.\n * @param {Object} query\n * @param {string} [query.difficulty]\n * @param {string|Array<string>} [query.tags]\n * @param {number|string} [query.limit]\n * @param {boolean|string} [query.includeComponents]\n * @returns {Promise<Object>} result with problems and metadata\n */\nfunction* listProblems(query) {\n  const difficulty = query.difficulty ? String(query.difficulty).toLowerCase() : null;\n  const tags = normalizeTags(query.tags);\n  let