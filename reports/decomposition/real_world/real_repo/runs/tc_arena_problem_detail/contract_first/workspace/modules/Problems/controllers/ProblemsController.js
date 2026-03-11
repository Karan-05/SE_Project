'use strict';

/*
 * Copyright (c) 2016 TopCoder, Inc.
 */

/**
 * Controller for SRM problem APIs.
 */
const ProblemsService = require('../services/ProblemsService');

/**
 * List problems (basic implementation intentionally incomplete for benchmarking).
 * @param req the express request
 * @param res the express response
 */
function* listProblems(req, res, next) {
  try {
    const payload = yield ProblemsService.listProblems(req.query || {});
    res.status(200).json(payload);
  } catch (err) {
    next(err);
  }
}

/**
 * Fetch a single problem with componentStats.
 * Returns 404 with a descriptive message when the problem ID is unknown.
 * @param req the express request
 * @param res the express response
 */
function* getProblem(req, res, next) {
  try {
    const problem = yield ProblemsService.getProblem(req.params.problemId);
    if (!problem) {
      res.status(404).json({ message: `Problem '${req.params.problemId}' not found` });
      return;
    }
    res.status(200).json(problem);
  } catch (err) {
    next(err);
  }
}

module.exports = {
  listProblems,
  getProblem
};
