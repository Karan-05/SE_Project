'use strict';

const { expect } = require('chai');
const co = require('co');
const ProblemsController = require('../modules/Problems/controllers/ProblemsController');

function invokeList(query = {}) {
  return new Promise((resolve, reject) => {
    let statusCode = 200;
    const req = { query };
    const res = {
      status(code) {
        statusCode = code;
        return this;
      },
      json(body) {
        resolve({ status: statusCode, body });
      }
    };
    co(ProblemsController.listProblems(req, res, reject)).catch(reject);
  });
}

describe('SRM problem listing contract', () => {
  it('filters by difficulty, enforces limit, and emits metadata', async () => {
    const res = await invokeList({
      difficulty: 'easy',
      limit: 2,
      includeComponents: true
    });
    expect(res.status).to.equal(200);
    expect(res.body).to.be.an('object');
    expect(res.body.metadata).to.deep.equal({
      totalProblems: 5,
      filteredCount: 3,
      appliedLimit: 2,
      difficultyBreakdown: {
        Easy: 3,
        Medium: 1,
        Hard: 1
      }
    });
    expect(res.body.problems).to.be.an('array').with.lengthOf(2);

    // Should be sorted by roundId ascending among the filtered set.
    expect(res.body.problems[0].id).to.equal('SRM-5003');
    expect(res.body.problems[1].id).to.equal('SRM-5001');

    res.body.problems.forEach((problem) => {
      expect(problem.difficulty).to.equal('Easy');
      expect(problem.componentLanguages)
        .to.be.an('array')
        .that.is.not.empty;
      expect(problem.componentLanguages).to.eql(
        [...problem.componentLanguages].sort((a, b) =>
          a.localeCompare(b, 'en', { sensitivity: 'base' })
        )
      );
    });
  });
});
