# Triage Summary — universal_demo

## Bad Test Parsing (15/17)
- **Task** 30377081 (challenge_data_demoData.json)
  Strategy path: contract_first -> ... -> semantic_diff | Attempts: 10.0
  Failure: ed3d38c257f82b488a5149fc6160ac7019f956f26e77eea2afb7fc9fde6694f1 | Tests: synthesized (call)
  Problem snippet: We’re seeking a highly skilled **Azure Integration Developer** for a **remote** full-time engagement. This is a 6-month opportunity, with the possibility of extension based on performance and project needs.. This role is ideal for a deve...
  Failures: basic_integration_workflow: expected {'status': 'success', 'result': 'integration_completed'} but got None (error=), event_driven_workflow: expected {'status': 'success', 'result': 'event_processed'} but got None (error=), error_handling_integration: expected {'status': 'error', 'message': 'integration_failed'} but got None (error=)
- **Task** 155973f9-8d1b-41d2-b55f-7e7950552118 (data_processed_tasks.parquet)
  Strategy path: contract_first -> ... -> semantic_diff | Attempts: 10.0
  Failure: 15bc755a2165ad446c063795abd7bf7ecf75d7d209a575eb83478ba300bf8efb | Tests: synthesized (call)
  Problem snippet: Developer Opportunity for FICO Falcon Engineer
  Failures: basic_deployment: expected 'Deployment successful' but got None (error=), multi_tenant_setup: expected 'Multi-tenant setup successful' but got None (error=), rule_deployment: expected 'Rules deployed successfully' but got None (error=)
- **Task** 305e0763-dd63-4883-9133-55504503953d (data_raw_tasks.csv)
          Strategy path: contract_first -> ... -> semantic_diff | Attempts: 10.0
          Failure: 005c973bc62df6599b59a10586e414beaa87358587e6f292f9048f969924fb7f | Tests: synthesized (call)
          Problem snippet: This is the **HARD 1000 Points Competition**

By now you have built the base of the application. It's time to add more and complete the existing functionality \
 \
 \
**You are required to use ReactJS as the frontend technology. You may ...
          Failures: create_learning_space_valid: expected {'success': True, 'message': 'Learning space created successfully.'} but got None (error=), create_learning_space_missing_fields: expected {'success': False, 'message': 'Title is required.'} but got None (error=), create_post_valid: expected {'success': True, 'message': 'Post created successfully.'} but got None (error=)
- **Task** 305e0763-dd63-4883-9133-55504503953d (data_raw_tasks.csv)
          Strategy path: contract_first -> ... -> semantic_diff | Attempts: 10.0
          Failure: 005c973bc62df6599b59a10586e414beaa87358587e6f292f9048f969924fb7f | Tests: synthesized (call)
          Problem snippet: This is the **HARD 1000 Points Competition**

By now you have built the base of the application. It's time to add more and complete the existing functionality \
 \
 \
**You are required to use ReactJS as the frontend technology. You may ...
          Failures: create_learning_space_valid: expected {'success': True, 'message': 'Learning space created successfully.'} but got None (error=), create_learning_space_missing_fields: expected {'success': False, 'message': 'Title is required.'} but got None (error=), create_post_valid: expected {'success': True, 'message': 'Post created successfully.'} but got None (error=)
- **Task** 56b3df85-e4f4-40ab-a975-2a9e6810866e (data_processed_tasks.parquet)
  Strategy path: contract_first -> ... -> semantic_diff | Attempts: 10.0
  Failure: 0c2b6a1381a1cc4f6b69cfb3d077fe880e19b37dabe79fb838c54ed6b66158db | Tests: synthesized (call)
  Problem snippet: Topcoder Review API - Challenge and Resource API Integration
  Failures: valid_user_with_active_challenges: expected [{'challengeId': 'challenge1', 'status': 'ACTIVE', 'userRole': 'reviewer', 'reviewId': 'review1'}, {'challengeId': 'challenge2', 'status': 'ACTIVE', 'userRole': 'reviewer', 'reviewId': 'review2'}] but got None (error=), user_with_multiple_roles: expected [{'challengeId': 'challenge3', 'status': 'ACTIVE', 'userRole': 'submitter', 'reviewId': 'review3'}] but got None (error=), invalid_user_id: expected 'User not found' but got None (error=)

## Real Algorithm Wrong (2/17)
- **Task** 91e34246-16b8-417d-8eb6-f7dc38c9b320 (challenge_data_challengeData_2023-01-01_2023-01-31_page1.json)
          Strategy path: contract_first -> ... -> semantic_diff | Attempts: 10.0
          Failure: 6cd47f87e0cfbd57cf67f3001d19f3f31c2fac496e73804c5c0af469ef532fb3 | Tests: statement (io)
          Problem snippet: ## Overview
This is an old problem, related to TCO20. It is a great example of an RDM style problem. The only difference is that this practice round is *not* rated, and there is only one problem. Normal rated RDM rounds usually have thre...
          Failures: io_sample_1: expected No limitation
- Docker but got  (error=)
- **Task** graph_degree_test (experiments_decomposition_benchmark_tasks.json)
  Strategy path: contract_first -> ... -> semantic_diff | Attempts: 10.0
  Failure: 28bb4b22b791d684c93165572bd028c9665c7812af1096de8f618191ff494d2e | Tests: provided (call)
  Problem snippet: Return degree counts for each vertex.
  Failures: sample_0: expected {'0': 1, '1': 2, '2': 1} but got {0: 1, 1: 2, 2: 1} (error=), sample_1: expected {'1': 2} but got {1: 2} (error=)
