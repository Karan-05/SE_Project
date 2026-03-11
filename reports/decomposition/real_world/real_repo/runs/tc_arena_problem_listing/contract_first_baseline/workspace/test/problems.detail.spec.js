'use strict';

const { expect } = require('chai');
const co = require('co');
const ProblemsController = require('../modules/Problems/controllers/ProblemsController');

function invokeDetail(problemId) {
  return new Promise((resolve, reject) => {
    let statusCode = 200;
    const req = { params: { problemId } };
    const res = {
      status(code) {
        statusCode = code;
        return this;
      },
      json(body) {
        resolve({ status: statusCode, body });
      }
    };
    co(ProblemsController.getProblem(req, res, reject)).catch(reject);
  });
}

describe('SRM problem detail contract', () => {
  it('includes component statistics for SRM-5004', async () => {
    const res = await invokeDetail('SRM-5004');
    expect(res.status).to.equal(200);
    expect(res.body.id).to.equal('SRM-5004');
    expect(res.body.componentStats).to.deep.equal({
      languages: {
        cpp: 1,
        java: 1,
        python: 1
      },
      statusCounts: {
        ACTIVE: 3
      },
      maxPoints: 1000
    });
  });

  it('returns 404 when an SRM problem does not exist', async () => {
    const res = await invokeDetail('SRM-9999');
    expect(res.status).to.equal(404);
    expect(res.body).to.have.property('message').that.includes('SRM-9999');
  });
});
