```json
{
  "contract_review": [
    {
      "id": "component_stats_payload",
      "status": "covered",
      "plan": "Implement aggregation of componentStats.languages, statusCounts, and maxPoints in the service detail method, derived from the components array of the problem."
    },
    {
      "id": "error_handling",
      "status": "covered",
      "plan": "Return HTTP 404 with JSON { message } when the problemId does not exist in the service detail method."
    },
    {
      "id": "controller_service_boundary",
      "status": "covered",
      "plan": "Keep the controller thin by delegating all aggregation and error handling to the service, only forwarding the response or error to the HTTP layer."
    }
  ],
  "edits": [
    {
      "path": "modules/Problems/services/ProblemsService.js",
      "mode": "rewrite",
      "content": "'use strict';\n\n/*\n * Copyright (c) 2016 TopCoder, Inc.\n */\n\n/**\n * Service for SRM problem APIs.\n */\nconst fs = require('fs');\nconst path = require('path');\nconst Joi = require('joi');\nconst logger = require('../../../common/logger');\n\nlet cachedProblems;\n\nconst MAX_LIMIT = 50;\n\n/**\n * Normalize tags filter into a lowercase array.\n * @param {string|Array<string>} rawTags\n * @returns {Array<string>}\n */\nfunction normalizeTags(rawTags) {\n  if (!rawTags && rawTags !== '') {\n    return [];\n  }\n  const list = Array.isArray(rawTags) ? rawTags : String(rawTags).split(',');\n  return list\n    .map((tag) => String(tag || '').trim().toLowerCase())\n    .filter((tag) => tag);\n}\n\n/**\n * Check whether the problem contains at least one of the requested tags.\n * @param {Object} problem\n * @param {Array<string>} tags\n * @returns {boolean}\n */\nfunction problemHasTags(problem, tags) {\n  if (!tags || tags.length === 0) return true;\n  if (!problem.tags || !Array.isArray(problem.tags)) return false;\n  const problemTags = problem.tags.map((t) => t.toLowerCase());\n  return tags.some((tag) => problemTags.includes(tag));\n}\n\n/**\n * Load problems from data file, cache in memory.\n * @returns {Array<Object>}\n */\nfunction loadProblems() {\n  if (cachedProblems) return cachedProblems;\n  const dataPath = path.join(__dirname, '..', '..', '..', 'data', 'problems.json');\n  const raw = fs.readFileSync(dataPath, 'utf8');\n  cachedProblems = JSON.parse(raw);\n  return cachedProblems;\n}\n\n/**\n * Aggregate component statistics for a problem.\n * @param {Object} problem\n * @returns {Object} componentStats with languages, statusCounts, maxPoints\n */\nfunction aggregateComponentStats(problem) {\n  const componentStats = {\n    languages: {},\n    statusCounts: {},\n    maxPoints: 0\n  };\n  if (!problem.components || !Array.isArray(problem.components)) {\n    return componentStats;\n  }\n  for (const comp of problem.components) {\n    if (comp.language) {\