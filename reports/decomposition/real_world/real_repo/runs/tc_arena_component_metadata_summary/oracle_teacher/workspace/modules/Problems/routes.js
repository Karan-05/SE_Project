'use strict';

/*
 * Copyright (c) 2016 TopCoder, Inc.
 */

/**
 * Defines SRM problem routes.
 */
module.exports = {
  '/problems': {
    get: {
      controller: 'ProblemsController',
      method: 'listProblems'
    }
  },
  '/problems/:problemId': {
    get: {
      controller: 'ProblemsController',
      method: 'getProblem'
    }
  }
};
