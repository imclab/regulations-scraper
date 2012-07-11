GEVENT = False

from models import *

def run():
    import settings

    # grab a dictionary
    word_file = getattr(settings, 'WORD_FILE', '/usr/share/dict/words')
    english_words = set([word.strip() for word in open(word_file, 'r') if word and word[0] == word[0].lower()])

    from influenceexplorer import InfluenceExplorer
    api = InfluenceExplorer(settings.API_KEY, getattr(settings, 'AGGREGATES_API_BASE_URL', "http://transparencydata.com/api/1.0/"))

    entities = []
    for type in ['individual', 'organization', 'politician']:
        count = api.entities.count(type)
        for i in range(0, count, 10000):
            entities.extend(api.entities.list(i, i + 10000, type))

    from oxtail.matching.normalize import normalize_list
    for entity in entities:
        record = {
            'id': entity['id'],
            'td_type': entity['type'],
            'td_name': entity['name'],
            'aliases': normalize_list([entity['name']] + entity['aliases'], entity['type'])
        }
        record['filtered_aliases'] = [alias for alias in record['aliases'] if alias.lower() not in english_words]
        
        db_entity = Entity(**record)
        db_entity.save()

        print "Saved %s as %s" % (record['aliases'][0], record['id'])