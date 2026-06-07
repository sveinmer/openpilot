#!/usr/bin/env python3
# C3_F4_PANDA: regression tests for flash_panda()'s DFU fall-back.
#
# Background: the revived F4/DOS panda does not reliably honor the USB
# enter_bootstub request, so panda.flash() can fail its assert(self.bootstub).
# Before the fall-back fix, that AssertionError propagated out of flash_panda()
# and pandad crash-looped on every firmware-signature mismatch (USB flapping,
# red panda status in the UI). These tests pin the recovery behaviour without
# needing real hardware by mocking the Panda/HARDWARE boundary.
import sys
from unittest import mock

# pandad.py imports usb1 at module scope; stub it so the import works on hosts
# without libusb1 (the real Panda objects are mocked in every test anyway).
sys.modules.setdefault("usb1", mock.MagicMock())

from openpilot.selfdrive.pandad import pandad  # noqa: E402

EXPECTED = bytes.fromhex("223023b5a2eb4415")   # release-signed F4 firmware
WRONG = bytes.fromhex("759a2ceb502af7a5")      # stale DEBUG firmware


def _make_panda(*, flash_raises: bool, internal: bool = True, start_sig: bytes = WRONG,
                start_bootstub: bool = False, recover_works: bool = True):
  """Build a fake Panda whose signature/bootstub state mutates like real flashing."""
  p = mock.MagicMock()
  box = {"sig": start_sig}
  p.bootstub = start_bootstub
  p.is_internal.return_value = internal
  p.get_version.return_value = "DEV-test-DEBUG"
  p.get_signature.side_effect = lambda: box["sig"]

  def _flash():
    box["sig"] = EXPECTED
    p.bootstub = False
  p.flash.side_effect = AssertionError("enter_bootstub failed") if flash_raises else _flash

  def _recover(reset=True):
    if recover_works:
      box["sig"] = EXPECTED
      p.bootstub = False
    return recover_works
  p.recover.side_effect = _recover
  return p


def _patches(panda):
  return (
    mock.patch.object(pandad, "Panda", return_value=panda),
    mock.patch.object(pandad, "HARDWARE"),
    mock.patch.object(pandad, "get_expected_signature", return_value=EXPECTED),
    mock.patch.object(pandad, "check_panda_support", return_value=True),
  )


def _run(panda):
  p_panda, p_hw, p_sig, p_support = _patches(panda)
  with p_panda, p_hw as hw, p_sig, p_support:
    result = pandad.flash_panda("deadbeef")
  return result, hw


def test_f4_flash_failure_falls_back_to_dfu_recovery():
  # The core bug: flash() raises because the F4 won't enter bootstub.
  panda = _make_panda(flash_raises=True, internal=True)
  result, hw = _run(panda)

  panda.flash.assert_called_once()                 # we tried the cheap path first
  hw.recover_internal_panda.assert_called_once()   # GPIO -> DFU for internal panda
  panda.recover.assert_called_once_with(reset=False)
  assert result is panda                           # no AssertionError escaped


def test_normal_flash_success_skips_recovery():
  # Healthy path: flash() works, no DFU recovery should be attempted.
  panda = _make_panda(flash_raises=False, internal=True)
  result, hw = _run(panda)

  panda.flash.assert_called_once()
  hw.recover_internal_panda.assert_not_called()
  panda.recover.assert_not_called()
  assert result is panda


def test_up_to_date_does_not_flash_or_recover():
  # Signature already matches: neither flash nor recovery should run.
  panda = _make_panda(flash_raises=False, internal=True, start_sig=EXPECTED)
  result, hw = _run(panda)

  panda.flash.assert_not_called()
  hw.recover_internal_panda.assert_not_called()
  panda.recover.assert_not_called()
  assert result is panda


def test_external_panda_recovery_uses_usb_reset():
  # For a non-internal panda the GPIO recovery is skipped and recover() resets.
  panda = _make_panda(flash_raises=True, internal=False)
  result, hw = _run(panda)

  hw.recover_internal_panda.assert_not_called()
  panda.recover.assert_called_once_with(reset=True)
  assert result is panda


def test_unrecoverable_panda_still_raises():
  # If recovery genuinely fails (signature stays wrong), we must not silently
  # return a mis-flashed panda - the final signature check must raise.
  panda = _make_panda(flash_raises=True, internal=True, recover_works=False)
  p_panda, p_hw, p_sig, p_support = _patches(panda)
  raised = False
  with p_panda, p_hw, p_sig, p_support:
    try:
      pandad.flash_panda("deadbeef")
    except AssertionError:
      raised = True
  assert raised
