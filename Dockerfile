# A shelf that reads, and only reads.
#
# The image deliberately has nothing installed beyond the interpreter: the server is the
# standard library plus these modules, and the absence of Textual is the proof that the data
# layer has no UI dependency -- the import would fail here if it did. When markdown-it is
# absent, bookshelf_web falls back to its own small renderer rather than failing the route.
#
#	 docker build -t bookshelf-web .
#	 mkdir -p ~/shelf-sync && cp shelf.db ~/shelf-sync/
#	 docker run --rm -p 8080:8080 -e BOOKSHELF_TOKEN=dev -v ~/shelf-sync:/data:ro bookshelf-web
#	 open http://localhost:8080/?k=dev        # the token is required off loopback
#
# The internal bind is 0.0.0.0 because that is what a published port reaches; who can reach
# it is decided by -p (use -p 127.0.0.1:8080:8080 to keep it on this machine) and by the
# token. On a tailnet, the tailnet is the wall and the token is the second lock.
#
# The database is copied in, never shared live: the Mac stays the only writer. `:ro` on the
# mount and `mode=ro` in the connection are two independent refusals to write.

FROM python:3.13-slim

WORKDIR /srv

# Two pure-Python libraries, and they are the difference between a readable page and a
# crude one: markdown-it is the same renderer the terminal app uses (Textual depends on it),
# so a document comes out the same in both places, and Pygments colours code with the app's
# own palette. Both are optional at runtime -- the fallbacks stay -- but a browser without
# them is where "readability is awful" came from.
RUN pip install --no-cache-dir markdown-it-py pygments

COPY bookshelf_db.py bookshelf_repo.py bookshelf_scan.py bookshelf_tree.py \
     bookshelf_html.py bookshelf_web.py ./

EXPOSE 8080
ENV PYTHONUNBUFFERED=1

# 0.0.0.0 inside the container is fine: the published port decides who can reach it, and
# --token is still required by the server when the host is not loopback.
CMD ["python3", "bookshelf_web.py", "--db", "/data/shelf.db", "--host", "0.0.0.0", "--port", "8080"]
