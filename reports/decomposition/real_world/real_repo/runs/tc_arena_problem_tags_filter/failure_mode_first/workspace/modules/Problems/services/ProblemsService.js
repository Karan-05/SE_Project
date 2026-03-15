```json
{
  "contract_review": [
    {
      "id": "single_tag_filter",
      "status": "covered",
      "notes": "The code normalizes single tag filter input case-insensitively and returns metadata.appliedTags with lowercase tags."
    },
    {
      "id": "multi_tag_union",
      "status": "covered",
      "notes": "Comma-separated tags are split, normalized, and used to filter problems that contain any of the tags, exposing all normalized tags in metadata.appliedTags."
    },
    {
      "id": "array_tag_filter",
      "status": "covered",
      "notes": "The code supports tags[] array form alongside difficulty filters, preserving ordering by roundId and the paging limit."
    }
  ],
  "edits": [
    {
      "path": "modules/Problems/services/ProblemsService.js",
      "mode": "rewrite",
      "content": "'use strict';\n\n/*\n * Copyright (c) 2016 TopCoder, Inc.\n */\n\n/**\n * Service for SRM problem APIs.\n */\nconst fs = require('fs');\nconst path = require('path');\nconst Joi = require('joi');\nconst logger = require('../../../common/logger');\n\nlet cachedProblems;\n\nconst MAX_LIMIT = 50;\n\n/**\n * Normalize tags filter into a lowercase array.\n * @param {string|Array<string>} rawTags\n * @returns {Array<string>}\n */\nfunction normalizeTags(rawTags) {\n  if (!rawTags && rawTags !== '') {\n    return [];\n  }\n  const list = Array.isArray(rawTags) ? rawTags : String(rawTags).split(',');\n  return list\n    .map((tag) => String(tag || '').trim().toLowerCase())\n    .filter((tag) => tag);\n}\n\n/**\n * Check whether the problem contains at least one of the requested tags.\n * @param {Object} problem\n * @param {Array<string>} tags\n * @returns {boolean}\n */\nfunction problemHasAnyTag(problem, tags) {\n  if (!tags || tags.length === 0) {\n    return true;\n  }\n  if (!problem.metadata || !Array.isArray(problem.metadata.appliedTags)) {\n    return false;\n  }\n  // problem.metadata.appliedTags are normalized lowercase tags\n  return tags.some((tag) => problem.metadata.appliedTags.includes(tag));\n}\n\n/**\n * Load problems from JSON file and cache them.\n * @returns {Array<Object>}\n */\nfunction loadProblems() {\n  if (cachedProblems) {\n    return cachedProblems;\n  }\n  const filePath = path.resolve(__dirname, '../../data/problems.json');\n  const raw = fs.readFileSync(filePath, 'utf8');\n  const problems = JSON.parse(raw);\n  cachedProblems = problems;\n  return cachedProblems;\n}\n\n/**\n * List problems with optional filtering by difficulty and tags.\n * Supports ?tags=foo,bar or tags[]=foo&tags[]=bar forms.\n * Returns metadata with appliedTags normalized.\n * @param {Object} query\n * @returns {Promise<Object>} payload\n */\nfunction* listProblems(query) {\n  // Validate query params\n  const schema = Joi.object({\n    difficulty: Joi.string().valid('easy', 'medium', 'hard'),\n    tags: Joi.al