import time

import requests
from neo4j.v1 import GraphDatabase, basic_auth

import_query = """\
WITH {json} as data
UNWIND data.items as q
MERGE (question:Question {id:q.question_id})
  ON CREATE SET question.title = q.title, question.url = q.share_link, question.created = q.creation_date
SET question.favorites = q.favorite_count, question.updated = q.last_activity_date, question.views = q.view_count,
    question.upVotes = q.up_vote_count, question.downVotes = q.down_vote_count,
    question:Content, question:StackOverflow
FOREACH (q_owner IN [o in [q.owner] WHERE o.user_id IS NOT NULL] |
  MERGE (owner:StackOverflowAccount {id:q.owner.user_id}) ON CREATE SET owner.name = q.owner.display_name SET owner:User, owner:StackOverflow
  MERGE (owner)-[:POSTED]->(question)
)
FOREACH (tagName IN q.tags | MERGE (tag:Tag{name:tagName}) SET tag:StackOverflow MERGE (question)-[:TAGGED]->(tag))
FOREACH (a IN q.answers |
   MERGE (answer:Answer {id:a.answer_id})
   SET answer.accepted = a.is_accepted, answer.upVotes = a.up_vote_count, answer.downVotes = a.down_vote_count,
       answer:Content, answer:StackOverflow
   MERGE (question)<-[:ANSWERED]-(answer)
   FOREACH (a_owner IN filter(o IN [a.owner] where o.user_id is not null) |
     MERGE (answerer:User:StackOverflow {id:a_owner.user_id})
     ON CREATE SET answerer.name = a_owner.display_name
     SET answerer.reputation = a_owner.reputation, answerer.profileImage = a_owner.profile_image
     MERGE (answer)<-[:POSTED]-(answerer)
   )
)
"""

max_date_query = """\
MATCH (question:Question:Content:StackOverflow)
return question.created AS maxDate
ORDER BY question.created  DESC
limit 1
"""

class SOImporter:
    def __init__(self, neo4j_url, neo4j_user, neo4j_pass, so_key):
        self.neo4j_url = neo4j_url
        self.neo4j_user = neo4j_user
        self.neo4j_pass = neo4j_pass
        self.so_key = so_key

    def process_tag(self, tags, start_date, end_date):
        tag = ";".join(tags)

        print("Processing projects from {0} to {1}. Tag: [{2}]".format(start_date, end_date, tag))
        print(tag, start_date, end_date)

        with GraphDatabase.driver(self.neo4j_url, auth=basic_auth(self.neo4j_user, self.neo4j_pass)) as driver:
            with driver.session() as session:
                page = 1
                items = 100
                has_more = True

                while has_more:
                    api_url = self.construct_uri(page, items, tag, start_date, end_date, self.so_key)

                    response = requests.get(api_url, headers={"accept": "application/json"})
                    print(response.status_code)
                    if response.status_code != 200:
                        print(response.text)
                    json = response.json()
                    print("has_more", json.get("has_more", False), "quota", json.get("quota_remaining", 0))
                    if json.get("items", None) is not None:
                        print(len(json["items"]))
                        result = session.write_transaction(self.so_import, json)
                        print(result)
                        print(result.consume().counters)
                        page = page + 1

                    has_more = json.get("has_more", False)
                    print("has_more: {more} page {page}".format(page=page, more=has_more))
                    if json.get('quota_remaining', 0) <= 0:
                        time.sleep(10)
                    if json.get('backoff', None) is not None:
                        print("backoff", json['backoff'])
                        time.sleep(json['backoff'] + 5)

    @staticmethod
    def so_import(tx, json):
        return tx.run(import_query, json=json)

    def construct_uri(self, page, items, tag, from_date, to_date, so_key):
        api_url = "https://api.stackexchange.com/2.2/search?page={page}&pagesize={items}&order=asc&sort=creation&tagged={tag}&site=stackoverflow&key={key}&filter=!5-i6Zw8Y)4W7vpy91PMYsKM-k9yzEsSC1_Uxlf".format(
            tag=tag, page=page, items=items, key=so_key)

        if from_date is not None:
            api_url += "&fromdate={from_date}".format(from_date=from_date)

        if to_date is not None:
            api_url += "&todate={to_date}".format(to_date=to_date)

        return api_url


# def import_so(neo4j_url, neo4j_user, neo4j_pass, tag, so_key):
#     # importer = SOImporter(neo4j_url, neo4j_user, neo4j_pass, so_key)
#     # importer.process_date_range(tag, start_date, end_date)

#     with GraphDatabase.driver(neo4j_url, auth=basic_auth(neo4j_user, neo4j_pass)) as driver:
#         with driver.session() as session:
#             page = 1
#             items = 100
#             has_more = True

#             max_date = None
#             result = session.run(max_date_query)
#             if result.peek():
#                 max_date = result.peek()["maxDate"] - (60 * 60)

#             while has_more:
#                 api_url = construct_uri(page, items, tag, max_date, so_key)

#                 response = requests.get(api_url, headers={"accept": "application/json"})
#                 print(response.status_code)
#                 if response.status_code != 200:
#                     print(response.text)
#                 json = response.json()
#                 print("has_more", json.get("has_more", False), "quota", json.get("quota_remaining", 0))
#                 if json.get("items", None) is not None:
#                     print(len(json["items"]))
#                     result = session.run(import_query, {"json": json})
#                     print(result.consume().counters)
#                     page = page + 1

#                 has_more = json.get("has_more", False)
#                 print("has_more: {more} page {page}".format(page=page, more=has_more))
#                 if json.get('quota_remaining', 0) <= 0:
#                     time.sleep(10)
#                 if json.get('backoff', None) is not None:
#                     print("backoff", json['backoff'])
#                     time.sleep(json['backoff'] + 5)


# def construct_uri(page, items, tag, max_date, so_key):
#     api_url = "https://api.stackexchange.com/2.2/search?page={page}&pagesize={items}&order=asc&sort=creation&tagged={tag}&site=stackoverflow&key={key}&filter=!5-i6Zw8Y)4W7vpy91PMYsKM-k9yzEsSC1_Uxlf".format(
#         tag=tag, page=page, items=items, key=so_key)

#     if max_date is not None:
#         api_url += "&fromdate={max_date}".format(max_date=max_date)

#     return api_url
