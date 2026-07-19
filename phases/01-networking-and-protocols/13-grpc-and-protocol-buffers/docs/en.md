# gRPC & Protocol Buffers

> JSON over HTTP sends field *names* as text on every request. gRPC sends numbered fields as compact binary over one multiplexed HTTP/2 connection — and it starts with a serialization format small enough to decode by hand.

**Type:** Build
**Languages:** Python
**Prerequisites:** Lessons 08 and 11 — HTTP and HTTP/2 (gRPC rides on HTTP/2). You should know that HTTP/2 (Hypertext Transfer Protocol version 2) multiplexes many independent streams over one TCP connection, and that a byte is 8 bits.
**Time:** ~90 minutes

## The Problem

You have two services that need to talk. The default answer in 2015 was REST
(Representational State Transfer): JSON (JavaScript Object Notation) over
HTTP/1.1. It works, but look at what goes on the wire for a single user record:

```json
{"id": 150, "name": "Ada"}
```

Every request re-sends the strings `"id"` and `"name"`, re-parses them as text,
and opens the door to type drift — is `id` a number or a string this time? For
one call it is nothing. For a fleet of services exchanging millions of messages a
second, you are paying to ship the same field names over and over, and paying
again to parse text into numbers on both ends.

Two ideas fix this. First, stop sending field *names*: agree on a schema up front
where each field has a **number**, and put only the numbers on the wire. Second,
stop treating a remote call as a document you fetch — treat it as a **function you
call**, with typed arguments and a typed return, over a connection built for many
calls at once. Those two ideas are **Protocol Buffers** and **gRPC**. This lesson
builds the first one byte by byte, then shows exactly how the second wraps it.

## The Concept

### RPC: calling a function on another machine

**RPC** (Remote Procedure Call) is an old idea: make a call to another machine
*look* like calling a local function. Instead of `user = db.get_user(150)` hitting
a local object, the call is serialized, sent over the network, executed on a
server, and the return value is sent back — but your code still reads like a
function call. The framework hides the sockets.

For that illusion to work, both sides must agree on three things: the **name** of
the procedure, the **shape** of its arguments, and the **shape** of its return
value. That agreement is written in an **IDL** (Interface Definition Language). In
gRPC the IDL is a `.proto` file, and the message shapes it describes are
serialized with Protocol Buffers.

### Protocol Buffers: numbered fields, not named

**Protocol Buffers** ("protobuf") is Google's binary serialization format. You
declare your messages in a schema where every field has a **number**:

```text
message Person {
  int32  id   = 1;   // the "= 1" is the field NUMBER, not a default value
  string name = 2;
}
```

The field numbers are the contract. On the wire, protobuf never sends the names
`id` or `name` — it sends field *1* and field *2*. That is why the encoding is
compact, and why it is **forward- and backward-compatible**: you can add field 3
later, and old readers simply skip a number they don't recognize. Renaming a
field in the schema changes nothing on the wire; changing its number breaks
everything. Numbers, not names, are the identity.

### The wire format: tags, wire types, and varints

Each field on the wire is a **key** (called the *tag*) followed by a **value**.
The tag is a single integer that packs the field number and a *wire type*
together:

```text
tag = (field_number << 3) | wire_type
```

The low 3 bits are the **wire type** — how to read the bytes that follow — and
the rest is the field number. There are four wire types in use (types 3 and 4
were "groups", now deprecated):

| Wire type | Name | Reads as | Used for |
|---|---|---|---|
| `0` | VARINT | a variable-length integer | `int32`, `int64`, `uint32`, `uint64`, `sint32/64`, `bool`, `enum` |
| `1` | I64 (64-bit) | exactly 8 bytes, little-endian | `fixed64`, `sfixed64`, `double` |
| `2` | LEN (length-delimited) | a varint length, then that many bytes | `string`, `bytes`, embedded messages, packed repeated fields |
| `5` | I32 (32-bit) | exactly 4 bytes, little-endian | `fixed32`, `sfixed32`, `float` |

The workhorse is wire type 0, the **varint** (variable-length integer). A varint
stores 7 bits of value per byte. The 8th bit — the **MSB** (most significant bit)
— is a *continuation flag*: `1` means "another byte follows", `0` means "this is
the last byte". So the integer `1` takes one byte, and so does anything up to
`127`; you only spend a second byte once the value crosses 128. Small numbers are
cheap, which is exactly what you want when most IDs, counts, and enums are small.

Here is the classic example, the one you will produce in code below. Encoding
`Person{ id: 150, name: "Ada" }` yields **8 bytes**:

| Bytes (hex) | Meaning |
|---|---|
| `08` | tag: `(1 << 3) \| 0` → field #1, wire type 0 (varint) |
| `96 01` | varint value `150` (see below for why it is two bytes) |
| `12` | tag: `(2 << 3) \| 2` → field #2, wire type 2 (length-delimited) |
| `03` | length: the string is 3 bytes long |
| `41 64 61` | `"Ada"` in UTF-8 |

Why does `150` become `96 01`? In binary `150` is `1001 0110`. Split into 7-bit
groups, least-significant first: `0010110` and `0000001`. Set the continuation
flag on all but the last: `1_0010110` = `0x96`, then `0_0000001` = `0x01`. Decode
by stripping the flags and re-joining the 7-bit groups. That is the entire
algorithm, and you are about to write it.

### gRPC: protobuf messages as RPC over HTTP/2

**gRPC** is Google's RPC framework: it takes your `.proto` service definition,
generates client and server code, and moves protobuf messages between them over
**HTTP/2**. HTTP/2 matters because it multiplexes many independent request/response
**streams** over a single TCP (Transmission Control Protocol) connection, so
thousands of concurrent calls share one socket without head-of-line blocking
between calls.

A single gRPC message does not go on the wire naked. gRPC wraps it in a
**Length-Prefixed-Message**: one compression-flag byte, then a 4-byte big-endian
length, then the protobuf bytes — all carried inside HTTP/2 DATA frames. A unary
(one request, one response) call looks like this:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 404" width="100%" style="max-width:780px" role="img" aria-label="A gRPC unary call over one HTTP/2 stream. The client and server share one HTTP/2 stream on a shared TCP connection. The client sends a HEADERS frame with method POST, path slash pb dot Greeter slash SayHello, and content-type application slash grpc. It then sends a DATA frame carrying the length-prefixed protobuf message id 150, name Ada. The server runs SayHello on the request, then replies with a HEADERS frame status 200, a DATA frame with the length-prefixed protobuf reply, and a final HEADERS trailers frame carrying grpc-status 0. A grpc-status of 0 means OK and the stream is then closed.">
  <defs>
    <marker id="l13-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">A gRPC unary call over one HTTP/2 stream</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="90" y="44" width="140" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="570" y="44" width="140" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <text x="160" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Client</text>
    <text x="640" y="63" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Server</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M160 74 L160 364"/>
      <path d="M640 74 L640 364"/>
    </g>
    <!-- note band 1: transport context -->
    <rect x="70" y="88" width="660" height="22" rx="6" fill="#7f7f7f" fill-opacity="0.1" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="400" y="103" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">One HTTP/2 stream on a shared TCP connection</text>
    <!-- arrows -->
    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M166 144 L634 144" marker-end="url(#l13-ar)"/>
      <path d="M166 186 L634 186" marker-end="url(#l13-ar)"/>
      <path d="M634 248 L166 248" marker-end="url(#l13-ar)"/>
      <path d="M634 290 L166 290" marker-end="url(#l13-ar)"/>
      <path d="M634 332 L166 332" marker-end="url(#l13-ar)"/>
    </g>
    <!-- message 1: HEADERS (client -> server) -->
    <text x="400" y="128" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">HEADERS</text>
    <text x="400" y="138" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">:method POST&#8195;:path /pb.Greeter/SayHello&#8195;content-type application/grpc</text>
    <!-- message 2: DATA (client -> server) -->
    <text x="400" y="170" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">DATA</text>
    <text x="400" y="180" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">[flag=0]&#8201;[len=8]&#8201;[protobuf: id=150, name=&quot;Ada&quot;]</text>
    <!-- note band 2: server processing -->
    <rect x="70" y="196" width="660" height="22" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="400" y="211" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Server runs SayHello(request)</text>
    <!-- message 3: HEADERS (server -> client) -->
    <text x="400" y="232" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">HEADERS</text>
    <text x="400" y="242" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">:status 200&#8195;content-type application/grpc</text>
    <!-- message 4: DATA (server -> client) -->
    <text x="400" y="274" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">DATA</text>
    <text x="400" y="284" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">[flag=0]&#8201;[len=N]&#8201;[protobuf: the reply message]</text>
    <!-- message 5: HEADERS trailers (server -> client) -->
    <text x="400" y="316" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">HEADERS (trailers)</text>
    <text x="400" y="326" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">grpc-status: 0</text>
    <!-- note band 3: clean close -->
    <rect x="70" y="342" width="660" height="22" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="400" y="357" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">grpc-status 0 = OK &#8212; the stream is now closed</text>
    <!-- footer takeaway -->
    <text x="400" y="386" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">gRPC = HEADERS + length-prefixed protobuf DATA frames + a trailer carrying grpc-status, all on one HTTP/2 stream.</text>
  </g>
</svg>
```

The request path `/pb.Greeter/SayHello` is `/<package>.<Service>/<Method>` — the
RPC's name, straight from the `.proto`. The final **trailers** (a second HEADERS
frame after the body) carry `grpc-status`; a non-zero status is how gRPC reports
errors, since the HTTP `:status` is almost always 200 once the stream opens.

### The four call types

Because HTTP/2 streams are bidirectional, gRPC is not limited to one-shot calls.
A method can stream on either side:

| Call type | Request | Response | Good for |
|---|---|---|---|
| Unary | 1 message | 1 message | `GetUser(id) -> User` — an ordinary function call |
| Server streaming | 1 message | a stream | `Subscribe(topic) -> stream Event` — the server pushes updates |
| Client streaming | a stream | 1 message | `Upload(stream Chunk) -> Ack` — send a large input in pieces |
| Bidirectional streaming | a stream | a stream | `Chat(stream Msg) -> stream Msg` — both talk at once |

All four use the same framing you build here; they differ only in how many
Length-Prefixed-Messages flow in each direction before the stream closes.

## Build It

The full implementations are in [`code/`](../code/). Both files are
self-contained: each encodes something, decodes it back, asserts the round trip,
prints the bytes, and exits. Run them and watch a "binary format" turn into a
handful of bytes you can read.

### The protobuf wire format by hand

[`code/protobuf_wire.py`](../code/protobuf_wire.py) is the core of the lesson. It
implements the varint codec and the tag scheme with nothing but integers and bit
math:

```python
def encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        seven_bits = value & 0x7F      # take the low 7 bits
        value >>= 7                    # shift them off
        if value:                      # more bits remain -> set the MSB flag
            out.append(seven_bits | 0x80)
        else:                          # last group -> flag stays 0
            out.append(seven_bits)
            break
    return bytes(out)

def encode_tag(field_number: int, wire_type: int) -> bytes:
    return encode_varint((field_number << 3) | wire_type)
```

Encoding the `Person` message is then just: tag, value, tag, length, bytes.
Decoding reverses it — read a varint tag, split out `field_number = tag >> 3` and
`wire_type = tag & 0x07`, and dispatch on the wire type. Run it:

```bash
python3 code/protobuf_wire.py
```

It prints the exact 8 bytes `08 96 01 12 03 41 64 61`, decodes them back to
`{1: 150, 2: 'Ada'}`, asserts the round trip, and then shows the varint size
growing as the number does — `1` in one byte, `128` in two, `16384` in three.
That size table *is* the reason protobuf is compact.

### Framing a message the way gRPC does

[`code/grpc_frame.py`](../code/grpc_frame.py) takes the protobuf bytes and wraps
them in the gRPC Length-Prefixed-Message, so you can see how the serialization
format from the first file becomes a gRPC payload:

```python
import struct

def grpc_frame(message: bytes, compressed: bool = False) -> bytes:
    flag = 1 if compressed else 0
    # 1 flag byte + 4-byte big-endian length + the message bytes
    return struct.pack(">BI", flag, len(message)) + message
```

```bash
python3 code/grpc_frame.py
```

It prints `00 00 00 00 08` followed by the 8 protobuf bytes — the 5-byte prefix
that gRPC puts in front of every message inside an HTTP/2 DATA frame — then parses
it back and asserts the payload survived intact.

## Use It

In production you do not hand-roll varints. You write the `.proto`, run the
protobuf compiler (`protoc`) to generate typed classes and client/server stubs,
and call the generated method — the framework does the encoding and the HTTP/2
framing you just built. The schema and the call read like this (illustrative; the
generated code is what actually runs):

```text
syntax = "proto3";
package pb;

message HelloRequest  { int32 id = 1; string name = 2; }
message HelloReply    { string message = 1; }

service Greeter {
  rpc SayHello (HelloRequest) returns (HelloReply);   // a unary call
}
```

```python
# After `protoc` generates greeter_pb2 / greeter_pb2_grpc, a client call is:
with grpc.insecure_channel("localhost:50051") as channel:      # one HTTP/2 connection
    stub = greeter_pb2_grpc.GreeterStub(channel)
    reply = stub.SayHello(greeter_pb2.HelloRequest(id=150, name="Ada"))
    print(reply.message)
```

That one line, `stub.SayHello(...)`, does everything the two Build-It files did:
serialize the request to protobuf, length-prefix it, open an HTTP/2 stream, send
the HEADERS and DATA, read the reply DATA and trailers, and hand you back a typed
object. Because you built the wire format by hand, none of it is magic — you know
that `id=150` is the three bytes `08 96 01`, and that a `grpc-status: 0` trailer is
how the server said "OK".

The payoff of the numbered-field design shows up when the schema evolves. Add
`string email = 3;` to `HelloRequest` and deploy the new client against the old
server: the old server sees field 3, doesn't know it, and skips it — no crash, no
version negotiation. That forward/backward compatibility is why protobuf and gRPC
became the default for internal service-to-service APIs.

## Ship It

The artifact for this lesson is a schema-and-API design prompt:
[`outputs/prompt-grpc-protobuf-design.md`](../outputs/prompt-grpc-protobuf-design.md).
It walks from a service you want to expose to a concrete `.proto`: how to number
fields for compatibility, when to pick each wire-friendly scalar type, which of
the four call types fits the interaction, and the compatibility rules you must not
break once clients ship. You can apply it because you have seen what those field
numbers become on the wire.

## Key takeaways

- **RPC** makes a network call look like a local function call; both sides agree on the procedure name and the argument/return shapes via an **IDL** — for gRPC, a `.proto` file.
- **Protocol Buffers** puts **numbered fields**, not names, on the wire. Each field is a tag `(field_number << 3) | wire_type` followed by the value; that numbering is what makes the format compact and forward/backward compatible.
- **Varints** store 7 bits per byte with the high bit as a continuation flag, so small integers take few bytes — `150` encodes to just `96 01`.
- The four **wire types** in use are `0` VARINT, `1` I64, `2` LEN (length-delimited), and `5` I32; the wire type tells the reader how to consume the bytes after the tag.
- **gRPC** carries protobuf messages as length-prefixed frames over **HTTP/2** streams, supporting four call shapes: unary, server-streaming, client-streaming, and bidirectional-streaming.
