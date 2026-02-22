#!/usr/bin/env bash
set -euo pipefail

# Apply a Home Assistant config pack for:
# - Reolink device control scripts (privacy/PTZ/record)
# - Reolink -> AIHub automations (animal/person triggers)
# - AIHub rest_command endpoints
#
# Why sudo:
# data/homeassistant/* is owned by root in this setup.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HA_DIR="${ROOT_DIR}/data/homeassistant"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [[ ! -d "${HA_DIR}" ]]; then
  echo "Missing Home Assistant dir: ${HA_DIR}" >&2
  exit 1
fi

echo "Creating backups in ${HA_DIR}/backup_${STAMP}"
sudo install -d -m 0755 "${HA_DIR}/backup_${STAMP}"
for f in configuration.yaml automations.yaml scripts.yaml; do
  if [[ -f "${HA_DIR}/${f}" ]]; then
    sudo cp -a "${HA_DIR}/${f}" "${HA_DIR}/backup_${STAMP}/${f}"
  fi
done

cat <<'YAML' | sudo tee "${HA_DIR}/configuration.yaml" >/dev/null
# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml

# Local API calls from Home Assistant to AIHub on the internal Docker network.
rest_command:
  aihub_camera_event:
    url: "http://aihub:8080/v1/events/camera"
    method: post
    content_type: "application/json"
    payload: >
      {
        "event_id": "{{ event_id }}",
        "type": "{{ event_type }}",
        "camera": "{{ camera | default('reolink_e1pro') }}",
        "confidence": {{ confidence | default(0.9) }}
      }
  aihub_audio_wake:
    url: "http://aihub:8080/v1/events/audio/wake"
    method: post
    content_type: "application/json"
    payload: >
      {
        "device": "{{ device | default('reolink_mic') }}",
        "wake_phrase": "{{ wake_phrase | default('hej codex') }}"
      }

tts:
  - platform: aihub_chatterbox
    name: Chatterbox Lokal
    url: http://chatterbox-tts:8000/tts
    model: chatterbox
    voice: clone:sv_ref.wav
    response_format: wav
    language: sv
    timeout: 120
YAML

cat <<'YAML' | sudo tee "${HA_DIR}/scripts.yaml" >/dev/null
camera_privacy_on:
  alias: Camera privacy on
  mode: single
  sequence:
    - action: switch.turn_on
      target:
        entity_id: switch.living_room_sekretesslage

camera_privacy_off:
  alias: Camera privacy off
  mode: single
  sequence:
    - action: switch.turn_off
      target:
        entity_id: switch.living_room_sekretesslage

camera_record_30s:
  alias: Camera record 30s
  mode: restart
  sequence:
    - action: switch.turn_on
      target:
        entity_id: switch.living_room_spela_in
    - delay: "00:00:30"
    - action: switch.turn_off
      target:
        entity_id: switch.living_room_spela_in

camera_ptz_home:
  alias: Camera PTZ home
  mode: single
  sequence:
    - action: button.press
      target:
        entity_id: button.living_room_aterga_till_skyddspunkt

camera_ptz_left_short:
  alias: Camera PTZ left short
  mode: restart
  sequence:
    - action: button.press
      target:
        entity_id: button.living_room_ptz_vanster
    - delay: "00:00:01"
    - action: button.press
      target:
        entity_id: button.living_room_ptz_stopp

camera_ptz_right_short:
  alias: Camera PTZ right short
  mode: restart
  sequence:
    - action: button.press
      target:
        entity_id: button.living_room_ptz_hoger
    - delay: "00:00:01"
    - action: button.press
      target:
        entity_id: button.living_room_ptz_stopp

aihub_wake_hej_codex:
  alias: AIHub wake (hej codex)
  mode: single
  sequence:
    - action: rest_command.aihub_audio_wake
      data:
        device: reolink_mic
        wake_phrase: hej codex
YAML

cat <<'YAML' | sudo tee "${HA_DIR}/automations.yaml" >/dev/null
- id: reolink_enable_record_audio_on_start
  alias: Reolink ensure record audio on HA start
  trigger:
    - platform: homeassistant
      event: start
  action:
    - action: switch.turn_on
      target:
        entity_id: switch.living_room_spela_in_ljud
  mode: single

- id: reolink_animal_to_aihub
  alias: Reolink animal event -> AIHub
  trigger:
    - platform: state
      entity_id: binary_sensor.living_room_djur
      to: "on"
      for: "00:00:01"
  condition:
    - condition: state
      entity_id: switch.living_room_sekretesslage
      state: "off"
  action:
    - variables:
        aihub_event_id: "evt-dog-{{ now().strftime('%Y%m%d%H%M%S') }}"
    - action: rest_command.aihub_camera_event
      data:
        event_id: "{{ aihub_event_id }}"
        event_type: dog_detected
        camera: reolink_e1pro
        confidence: 0.92
    - action: persistent_notification.create
      data:
        title: "AI-Cam: animal event"
        message: "Dog/animal detected and forwarded to AIHub."
  mode: single

- id: reolink_person_to_aihub
  alias: Reolink person event -> AIHub
  trigger:
    - platform: state
      entity_id: binary_sensor.living_room_person
      to: "on"
      for: "00:00:01"
  condition:
    - condition: state
      entity_id: switch.living_room_sekretesslage
      state: "off"
  action:
    - variables:
        aihub_event_id: "evt-person-{{ now().strftime('%Y%m%d%H%M%S') }}"
    - action: rest_command.aihub_camera_event
      data:
        event_id: "{{ aihub_event_id }}"
        event_type: person_detected
        camera: reolink_e1pro
        confidence: 0.90
  mode: single

- id: reolink_privacy_mode_stops_recording
  alias: Reolink privacy on -> stop camera recording
  trigger:
    - platform: state
      entity_id: switch.living_room_sekretesslage
      to: "on"
  action:
    - action: switch.turn_off
      target:
        entity_id:
          - switch.living_room_spela_in
          - switch.living_room_spela_in_ljud
  mode: single
YAML

echo "Applied HA pack."
echo "Next:"
echo "  1) docker compose restart homeassistant"
echo "  2) In HA UI: Settings -> Devices & Services -> AIHub Conversation -> set wake phrase to 'hej codex'"
