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

describe('SRM problem tag filters', () => {
  it('filters by a single tag case-insensitively', async () => {
    const res = await invokeList({ tags: 'GRID' });
    expect(res.status).to.equal(200);
    expect(res.body.metadata.appliedTags).to.deep.equal(['grid']);
    expect(res.body.metadata.filteredCount).to.equal(1);
    expect(res.body.problems).to.have.lengthOf(1);
    expect(res.body.problems[0].id).to.equal('SRM-5003');
    expect(res.body.problems[0].tags).to.include('grid');
  });

  it('accepts comma-separated tags and returns merged results', async () => {
    const res = await invokeList({ tags: 'game,queue' });
    expect(res.status).to.equal(200);
    const ids = res.body.problems.map((p) => p.id);
    expect(ids).to.include('SRM-5004');
    expect(ids).to.include('SRM-5005');
    expect(res.body.metadata.filteredCount).to.equal(2);
    expect(res.body.metadata.appliedTags).to.deep.equal(['game', 'queue']);
  });

  it('accepts array form and combines with difficulty filter', async () => {
    const res = await invokeList({ difficulty: 'easy', tags: ['simulation', 'queue'] });
    expect(res.status).to.equal(200);
    expect(res.body.metadata.filteredCount).to.equal(2);
    expect(res.body.problems).to.have.lengthOf(2);
    expect(res.body.problems[0].id).to.equal('SRM-5001'); // smallest roundId among matches
    const ids = res.body.problems.map((p) => p.id);
    expect(ids).to.include('SRM-5001');
    expect(ids).to.include('SRM-5005');
    res.body.problems.forEach((problem) => {
      expect(problem.tags.map((tag) => tag.toLowerCase())).to.satisfy((tags) =>
        tags.includes('simulation') || tags.includes('queue')
      );
    });
  });
});
