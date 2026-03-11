'use strict';

/*
 * Copyright (c) 2016 TopCoder, Inc.
 */

/**
 * Service for SRM problem APIs.
 */
const fs = require('fs');
const path = require('path');
const Joi = require('joi');
const logger = require('../../../common/logger');

let cachedProblems;

const MAX_LIMIT = 50;

/**
 * Normalize tags filter into a lowercase array.
 * @param {string|Array<string>} rawTags
 * @returns {Array<string>}
 */
function normalizeTags(rawTags) {
  if (!rawTags && rawTags !== '') {
    return [];
  }
  const list = Array.isArray(rawTags) ? rawTags : String(rawTags).split(',');
  return list
    .map((tag) => String(tag || '').trim().toLowerCase())
    .filter((tag) => tag);
}

/**
 * Check whether the problem contains at least one of the requested tags.
 * @param {Object} problem
 * @param {Array<string>} tags
 * @returns {boolean}
 */
function matchesTags(problem, tags) {
  if (!tags.length) {
    return true;
  }
  const problemTags = (problem.tags || []).map((tag) => String(tag).toLowerCase());
  return tags.some((tag) => problemTags.includes(tag));
}

/**
 * Load the static SRM problem dataset.
 * @returns {Array<Object>}
 */
function loadProblems() {
  if (!cachedProblems) {
    const file = path.join(__dirname, '../../../data/problems.json');
    const raw = fs.readFileSync(file, 'utf8');
    cachedProblems = JSON.parse(raw);
  }
  return cachedProblems;
}

/**
 * Return a filtered, sorted, and optionally component-enriched list of problems
 * with metadata summary.
 * Supports query params: difficulty (case-insensitive), limit (max 50),
 * includeComponents (adds sorted componentLanguages per problem).
 * @param {Object} query
 * @returns {{ metadata: Object, problems: Array<Object> }}
 */
function* listProblems(query) {
  logger.debug('Listing SRM problems with query %j', query);
  const problems = loadProblems();
  const normalizedTags = normalizeTags(query.tags);
  const includeComponents =
    query.includeComponents === true ||
    query.includeComponents === 'true' ||
    query.includeComponents === 1 ||
    query.includeComponents === '1';

  // Difficulty breakdown over the full dataset (canonical casing from data).
  const difficultyBreakdown = {};
  problems.forEach((p) => {
    difficultyBreakdown[p.difficulty] = (difficultyBreakdown[p.difficulty] || 0) + 1;
  });

  // Filter by difficulty (case-insensitive).
  let filtered = problems;
  if (query.difficulty) {
    const target = String(query.difficulty).toLowerCase();
    filtered = problems.filter((p) => p.difficulty.toLowerCase() === target);
  }

  // Filter by tags (case-insensitive, matches any requested tag).
  if (normalizedTags.length) {
    filtered = filtered.filter((problem) => matchesTags(problem, normalizedTags));
  }

  // Sort by roundId ascending.
  filtered = filtered.slice().sort((a, b) => a.roundId - b.roundId);
  const filteredCount = filtered.length;

  // Apply limit (capped at MAX_LIMIT).
  let requestedLimit = filteredCount;
  if (query.limit !== undefined && query.limit !== null) {
    const parsed = Number(query.limit);
    if (Number.isFinite(parsed) && parsed > 0) {
      requestedLimit = Math.min(Math.floor(parsed), MAX_LIMIT);
    }
  }
  const limited = filtered.slice(0, requestedLimit);

  // Build per-problem summaries.
  const aggregateLanguages = {};
  const aggregateStatuses = {};
  const summaries = limited.map((problem) => {
    const summary = {
      id: problem.id,
      name: problem.name,
      difficulty: problem.difficulty,
      roundId: problem.roundId,
      tags: problem.tags,
      totalSubmissions: problem.totalSubmissions,
    };
    if (includeComponents) {
      const langs = (problem.components || []).map((c) => c.language);
      const deduped = [...new Set(langs)].sort((a, b) =>
        a.localeCompare(b, 'en', { sensitivity: 'base' })
      );
      summary.componentLanguages = deduped;
      (problem.components || []).forEach((comp) => {
        const lang = comp.language;
        const status = comp.status || 'UNKNOWN';
        aggregateLanguages[lang] = (aggregateLanguages[lang] || 0) + 1;
        aggregateStatuses[status] = (aggregateStatuses[status] || 0) + 1;
      });
    }
    return summary;
  });

  const metadata = {
    totalProblems: problems.length,
    filteredCount,
    appliedLimit: summaries.length,
    difficultyBreakdown,
  };
  if (normalizedTags.length) {
    metadata.appliedTags = normalizedTags;
  }
  if (includeComponents) {
    metadata.componentLanguageTotals = aggregateLanguages;
    metadata.componentStatusTotals = aggregateStatuses;
  }

  return {
    metadata,
    problems: summaries,
  };
}

listProblems.schema = {
  query: Joi.object({
    difficulty: Joi.string().optional(),
    limit: Joi.number().integer().min(1).max(MAX_LIMIT).optional(),
    includeComponents: Joi.boolean().optional(),
    tags: Joi.alternatives().try(
      Joi.array().items(Joi.string()),
      Joi.string()
    ).optional()
  })
};

/**
 * Fetch a single SRM problem with aggregated componentStats.
 * Returns null when the problem ID is not found.
 * @param {String} problemId
 * @returns {Object|null}
 */
function* getProblem(problemId) {
  logger.debug('Fetching SRM problem %s', problemId);
  const problems = loadProblems();
  const problem = problems.find((p) => p.id === problemId);
  if (!problem) {
    return null;
  }

  // Aggregate component statistics.
  const languages = {};
  const statusCounts = {};
  let maxPoints = 0;
  (problem.components || []).forEach((comp) => {
    const lang = comp.language;
    languages[lang] = (languages[lang] || 0) + 1;
    const status = comp.status || 'UNKNOWN';
    statusCounts[status] = (statusCounts[status] || 0) + 1;
    if (typeof comp.points === 'number' && comp.points > maxPoints) {
      maxPoints = comp.points;
    }
  });

  return Object.assign({}, problem, {
    componentStats: { languages, statusCounts, maxPoints },
  });
}

getProblem.schema = {
  problemId: Joi.string().required()
};

module.exports = {
  listProblems,
  getProblem
};

logger.buildService(module.exports);
