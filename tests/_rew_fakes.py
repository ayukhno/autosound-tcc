"""REW's own answers, faked once for every test that stands in for REW at the method's edge.

One copy of each answer, because copies drift: two separate fakes of "no impulse" both answered as
no REW does, and both broke against the method's next release at once (#178).
"""

from __future__ import annotations

import urllib.error


def no_impulse(api, listing):
    """A stand-in for `rew_api.get_impulse_response` from a REW that keeps no impulse for the
    captures of `listing` (`{id: record}`, the shape of REW's `/measurements`).

    It answers as REW does, recorded at the skill's live pass at REW (2026-10-07,
    `rew_tool/testdata/rew/impulse-none.json`): HTTP 400 with "<title> at index <id> uuid <uuid>
    does not have an impulse response", naming the capture asked. It is not a 404 and not an error
    of ours. The method lets this one answer through, and counts any other failed impulse read on a
    sweep as an issue (v3.1.2). `api` is the `rew_api` module the request would have gone through.
    """

    def get_impulse_response(mid, normalised=False):
        held = listing[mid]
        url = (f"{api.BASE_URL}/measurements/{mid}/impulse-response"
               + ("" if normalised else "?normalised=false"))
        raise urllib.error.HTTPError(
            url, 400, f"{held['title']} at index {mid} uuid {held['uuid']} does not have an "
                      f"impulse response", {}, None)

    return get_impulse_response
