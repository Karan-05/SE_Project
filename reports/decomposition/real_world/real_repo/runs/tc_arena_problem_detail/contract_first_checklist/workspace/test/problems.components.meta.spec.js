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

describe('SRM component metadata summary', () => {
  it('aggregates language and status totals for filtered results', async () => {
    const res = await invokeList({ includeComponents: true, difficulty: 'easy' });
    expect(res.status).to.equal(200);
    expect(res.body.metadata.componentLanguageTotals).to.deep.equal({
      cpp: 1,
      java: 2,
      python: 3,
      ruby: 1,
      go: 1
    });
    expect(res.body.metadata.componentStatusTotals).to.deep.equal({
      ACTIVE: 8
    });
  });

  it('respects the applied limit when aggregating component metadata', async () => {
    const res = await invokeList({ includeComponents: true, difficulty: 'hard', limit: 1 });
    expect(res.status).to.equal(200);
    expect(res.body.metadata.appliedLimit).to.equal(1);
    expect(res.body.metadata.componentLanguageTotals).to.deep.equal({
      cpp: 1,
      java: 1,
      python: 1
    });
    expect(res.body.metadata.componentStatusTotals).to.deep.equal({
      ACTIVE: 3
    });
  });
});
