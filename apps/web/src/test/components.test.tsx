import { render, screen } from '@testing-library/react';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { PlannedView } from '../components/PlannedView';
import { AgentPanel } from '../components/AgentPanel';
import { AvatarOrb } from '../components/AvatarOrb';
import type { Edition } from '../api';

afterEach(() => { vi.restoreAllMocks(); });

test('simulated data is badged as simulated', () => {
  render(<ProvenanceBadge kind="simulated" />);
  expect(screen.getByText('Simulated')).toBeTruthy();
});

test('a planned edition says what it needs and shows no readings', () => {
  const ed: Edition = { id: 'rover', name: 'Ground Rover', tagline: 'Field survey', status: 'planned',
    products: ['ground-rover'], panels: ['agent'], agent_tools: ['list_devices'], data_source: 'MQTT station records',
    needs: 'A rover unit running the ROS 2 station publisher' };
  render(<PlannedView edition={ed} />);
  expect(screen.getByText(/ROS 2 station publisher/)).toBeTruthy();
  expect(screen.getByText(/No data source yet/)).toBeTruthy();
});

test('the agent works by text when the browser has no speech', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ llm_mode: 'local', model: 'm',
    available: true, reason: null, month_spend_usd: 0, monthly_cap_usd: null, data_notice: null }), { status: 200 }));
  render(<AgentPanel edition="xseed" open onClose={() => {}} />);
  expect(screen.getByLabelText('Question for CoSE_Agent')).toBeTruthy();
  expect(screen.queryByLabelText('Speak your question')).toBeNull();
  expect(await screen.findByText(/Voice input is not available/)).toBeTruthy();
});

test('the avatar announces its state', () => {
  render(<AvatarOrb state="thinking" />);
  expect(screen.getByRole('img', { name: /Looking at the data/ })).toBeTruthy();
});
