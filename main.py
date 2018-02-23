#!/usr/bin/python3

import praw
import os
import logging.handlers
import time
import sys
import configparser
import re
import traceback
import urllib.parse
import urllib.request
from datetime import datetime

### Config ###
LOG_FOLDER_NAME = "logs"
USER_AGENT = "ThreadIntegrityChecker reddit bot (by /u/Watchful1)"
REDDIT_OWNER = "Watchful1"


### Logging setup ###
LOG_LEVEL = logging.DEBUG
if not os.path.exists(LOG_FOLDER_NAME):
	os.makedirs(LOG_FOLDER_NAME)
LOG_FILENAME = LOG_FOLDER_NAME + "/" + "bot.log"
LOG_FILE_BACKUPCOUNT = 5
LOG_FILE_MAXSIZE = 1024 * 256

log = logging.getLogger("bot")
log.setLevel(LOG_LEVEL)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
log_stderrHandler = logging.StreamHandler()
log_stderrHandler.setFormatter(log_formatter)
log.addHandler(log_stderrHandler)
if LOG_FILENAME is not None:
	log_fileHandler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=LOG_FILE_MAXSIZE,
													       backupCount=LOG_FILE_BACKUPCOUNT)
	log_formatter_file = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
	log_fileHandler.setFormatter(log_formatter_file)
	log.addHandler(log_fileHandler)


log.debug("Connecting to reddit")

once = False
debug = False
user = None
if len(sys.argv) >= 2:
	user = sys.argv[1]
	for arg in sys.argv:
		if arg == 'once':
			once = True
		elif arg == 'debug':
			debug = True
else:
	log.error("No user specified, aborting")
	sys.exit(0)


try:
	reddit = praw.Reddit(
		user
		, user_agent=USER_AGENT)
except configparser.NoSectionError:
	log.error("User " + user + " not in praw.ini, aborting")
	sys.exit(0)

if reddit.config.CONFIG.has_option(user, 'pastebin'):
	pastebin_key = reddit.config.CONFIG[user]['pastebin']
else:
	log.error("Pastebin key not in config, aborting")
	sys.exit(0)


def paste(title, content):  # used for posting a new paste
	pastebin_vars = dict(
		api_option='paste',
		api_dev_key=pastebin_key,
		api_paste_name=title,
		api_paste_code=content,
	)
	return urllib.request.urlopen('http://pastebin.com/api/api_post.php', urllib.parse.urlencode(pastebin_vars).encode('utf8')).read()


def insertSorted(authorIn, tableIn, sort='none'):
	inserted = False
	if sort == 'age':
		for i, author in enumerate(tableIn):
			if author['age'] > authorIn['age']:
				tableIn.insert(i, authorIn)
				inserted = True
				break
	elif sort == 'ratio':
		for i, author in enumerate(tableIn):
			if authorIn['out'] == 0:
				if author['out'] == 0:
					if author['in'] > authorIn['in']:
						tableIn.insert(i, authorIn)
						inserted = True
						break
				else:
					tableIn.insert(i, authorIn)
					inserted = True
					break
			elif author['in'] - author['out'] < authorIn['in'] - authorIn['out']:
				tableIn.insert(i, authorIn)
				inserted = True
				break
	else:
		tableIn.append(authorIn)

	if not inserted:
		tableIn.append(authorIn)

	return tableIn


footer = "\n\n*****\n\nThis is a bot run by /u/Watchful1, it analyses threads and returns a summary of the authors of top level comments"


while True:
	try:
		for message in reddit.inbox.stream():
			startTime = time.perf_counter()
			log.debug("Processing message from: {}".format(str(message.author)))

			if isinstance(message, praw.models.Message):
				result = ""
				links = re.findall('(?:reddit.com/r/\w*/comments/)(\w*)', message.body.lower())
				if len(links) != 0:
					submission = None
					try:
						submission = reddit.submission(id=links[0])
					except Exception as err:
						result = "I found a link, but something went wrong when I tried to load the post"
						submission = None
						log.debug("Exception parsing link")

					if submission is not None:
						subreddit = str(submission.subreddit).lower()
						log.debug("Found submission in subreddit: {}".format(subreddit))
						comments = submission.comments
						moreCalls = 0
						while isinstance(comments[-1], praw.models.MoreComments):
							if moreCalls == 0:
								try:
									message.reply("This looks like a big thread, it might take a while"+footer)
								except Exception as err:
									log.debug("Exception replying to message")

							moreCalls += 1
							if moreCalls % 10 == 0:
								log.debug("More comments: {}".format(moreCalls))
							comments = comments[:-1] + comments[-1].comments()
						if moreCalls > 0:
							log.debug("More calls: {}".format(moreCalls))

						authors = set()
						for comment in comments:
							if comment.depth == 0 and comment.author is not None:
								authors.add(comment.author)

						authorObjects = []
						nameMaxLength = 0
						log.debug("Authors: 0 / {}".format(len(authors)))
						for i, author in enumerate(authors):
							if (i + 1) % 10 == 0:
								log.debug("Authors: {} / {}".format(i + 1, len(authors)))
							try:
								if not hasattr(author, 'created_utc'):
									log.debug("Bad redditor object: {}".format(author))
									continue
							except Exception as err:
								log.debug("Bad redditor object: {}".format(author))
								continue
							created = datetime.utcfromtimestamp(author.created_utc)
							now = datetime.utcnow()

							commentsCount = 0
							commentsInSub = 0
							commentsOutSub = 0
							for comment in author.new(limit=100):
								commentsCount += 1
								if str(comment.subreddit).lower() == subreddit:
									commentsInSub += 1
								else:
									commentsOutSub += 1

							authorObject = {'name': str(author), 'age': (now - created).days, 'in': commentsInSub, 'out': commentsOutSub}
							if len(authorObject['name']) > nameMaxLength:
								nameMaxLength = len(authorObject['name'])
							authorObjects = insertSorted(authorObject, authorObjects, 'age')

						if len(authors) % 10 != 0:
							log.debug("Authors: {} / {}".format(len(authors), len(authors)))
						authorString = []
						authorString.append("{}|Age |In/Out\n".format("Author".ljust(nameMaxLength)))
						for authorObject in authorObjects:
							string = "{}|{}|{}/{}".format(authorObject['name'].ljust(nameMaxLength), str(authorObject['age']).ljust(4), authorObject['in'], authorObject['out'])
							if debug:
								log.debug(string)
							authorString.append(string)
							authorString.append("\n")

						pasteoutput = paste("Thread summary: {}{}".format("https://www.reddit.com", submission.permalink), ''.join(authorString)).decode('utf-8')

						if "pastebin.com" in pasteoutput:
							log.debug("Finished pasting: {}".format(pasteoutput))
							result = "Finished processing in {} seconds, here's your summary: {}\n\nFormat is redditor name, " \
						         "age of account in days, then of their last 100 comments, how many are in the subreddit the " \
						         "thread is in versus how many are out of it".format(int(time.perf_counter() - startTime), pasteoutput)
						else:
							log.debug("Something went wrong pasting: {}".format(pasteoutput))
							result = "Something went wrong generating the pastebin of your summary. Please let /u/Watchful1 know"
					else:
						result = "I found a link, but something went wrong when I tried to load the post"
				else:
					result = "I couldn't find a link in your message"

				try:
					message.mark_read()
					message.reply(result+footer)
				except Exception as err:
					log.debug("Exception replying to message")
			else:
				log.debug("Marking comment as read")
				try:
					message.mark_read()
				except Exception as err:
					log.debug("Exception marking comment as read")

			log.debug("Message processed after: %d", int(time.perf_counter() - startTime))
			if once:
				break

	except Exception as err:
		log.warning("Hit an error in main loop")
		log.warning(traceback.format_exc())

	if once:
		break

	time.sleep(5 * 60)
