// ---------------------------------------------------------------------------
// Agentic Team Provisioning models
// ---------------------------------------------------------------------------

export type TriggerType = 'message' | 'event' | 'schedule' | 'manual';
export type StepType = 'action' | 'decision' | 'parallel_split' | 'parallel_join' | 'wait' | 'subprocess';
export type ProcessStatus = 'draft' | 'complete' | 'archived';

export interface ProcessStepAgent {
  agent_name: string;
  role: string;
}

export interface ProcessStep {
  step_id: string;
  name: string;
  description: string;
  step_type: StepType;
  agents: ProcessStepAgent[];
  next_steps: string[];
  condition?: string | null;
}

export interface ProcessTrigger {
  trigger_type: TriggerType;
  description: string;
}

export interface ProcessOutput {
  description: string;
  destination: string;
}

export interface ProcessDefinition {
  process_id: string;
  name: string;
  description: string;
  trigger: ProcessTrigger;
  steps: ProcessStep[];
  output: ProcessOutput;
  status: ProcessStatus;
}

export interface AgenticTeam {
  team_id: string;
  name: string;
  description: string;
  processes: ProcessDefinition[];
  created_at: string;
  updated_at: string;
}

// Request / response types

export interface CreateAgenticTeamRequest {
  name: string;
  description: string;
}

export interface CreateAgenticTeamResponse {
  team_id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface AgenticTeamSummary {
  team_id: string;
  name: string;
  description: string;
  process_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgenticTeamDetailResponse {
  team: AgenticTeam;
}

// Conversation types

export interface AgenticConversationMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface CreateAgenticConversationRequest {
  initial_message?: string | null;
  team_id: string;
}

export interface SendAgenticMessageRequest {
  message: string;
}

export interface AgenticConversationStateResponse {
  conversation_id: string;
  team_id: string;
  messages: AgenticConversationMessage[];
  current_process: ProcessDefinition | null;
  suggested_questions: string[];
}

export interface AgenticConversationSummary {
  conversation_id: string;
  team_id: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}
