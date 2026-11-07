import re

from typer.testing import CliRunner

from realliferail.cli.main import app

runner = CliRunner()


def test_board_demo():
    r = runner.invoke(app, ["board", "RDG", "--demo", "--time", "14:00"])
    assert r.exit_code == 0, r.output
    assert "Reading: departures 14:00 to 15:00" in r.output
    assert re.search(r"\d\d:\d\d\s+\S", r.output)


def test_board_json():
    r = runner.invoke(app, ["board", "RDG", "--demo", "--json", "--time", "14:00"])
    assert r.exit_code == 0
    assert '"station": "Reading"' in r.output


def test_train_demo():
    r = runner.invoke(app, ["board", "WAT", "--demo", "--json", "--time", "12:00"])
    uid = re.search(r'"id": "([^"]+)"', r.output).group(1)
    t = runner.invoke(app, ["train", uid, "--demo"])
    assert t.exit_code == 0, t.output
    assert "London Waterloo" in t.output
    np = runner.invoke(app, ["train", uid, "--demo", "--no-passes"])
    assert "(Hampton Court Jn)" in t.output and "(Hampton Court Jn)" not in np.output


def test_bad_station_is_a_sentence():
    r = runner.invoke(app, ["board", "RDG", "--demo", "--to", "zzqqxx"])
    assert r.exit_code == 1
    assert "Couldn't find a station" in r.output


def test_token_without_one_explains():
    r = runner.invoke(app, ["token"], env={"RTT_TOKEN": "", "HOME": "/nonexistent"})
    assert r.exit_code == 2
    assert "api-portal.rtt.io" in r.output
