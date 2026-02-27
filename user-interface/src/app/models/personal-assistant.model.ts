/**
 * Personal Assistant API models.
 */

/** Chat message in a conversation */
export interface AssistantMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

/** Assistant request body */
export interface AssistantRequest {
  message: string;
  context?: Record<string, unknown>;
}

/** Assistant response */
export interface AssistantResponse {
  request_id: string;
  message: string;
  response?: string;
  actions_taken?: string[];
  data?: Record<string, unknown>;
  follow_up_suggestions?: string[];
  timestamp: string;
}

/** Identity profile section */
export interface IdentityProfile {
  full_name?: string;
  preferred_name?: string;
  email?: string;
  phone?: string;
  timezone?: string;
  languages?: string[];
  communication_preference?: string;
  birthday?: string;
  address?: string;
}

/** Preferences profile section */
export interface PreferencesProfile {
  food_likes?: string[];
  food_dislikes?: string[];
  cuisines_ranked?: string[];
  dietary_restrictions?: string[];
  favorite_flowers?: string[];
  favorite_colors?: string[];
  brands_liked?: string[];
  brands_disliked?: string[];
  music_genres?: string[];
  hobbies?: string[];
}

/** Goals profile section */
export interface GoalsProfile {
  short_term_goals?: string[];
  long_term_goals?: string[];
  dreams?: string[];
  bucket_list?: string[];
  values?: string[];
}

/** Professional profile section */
export interface ProfessionalProfile {
  job_title?: string;
  company?: string;
  industry?: string;
  work_schedule?: string;
  work_timezone?: string;
  professional_goals?: string[];
  skills?: string[];
  networking_preferences?: string;
}

/** Full user profile */
export interface UserProfile {
  user_id: string;
  schema_version?: string;
  created_at?: string;
  updated_at?: string;
  identity?: IdentityProfile;
  preferences?: PreferencesProfile;
  goals?: GoalsProfile;
  professional?: ProfessionalProfile;
}

/** Profile update request */
export interface ProfileUpdateRequest {
  category: string;
  data: Record<string, unknown>;
  merge?: boolean;
}

/** Profile update response */
export interface ProfileUpdateResponse {
  success: boolean;
  updated_fields?: string[];
  message?: string;
}

/** Task item */
export interface TaskItem {
  item_id: string;
  description: string;
  quantity?: string;
  priority?: 'low' | 'medium' | 'high';
  due_date?: string;
  status?: 'pending' | 'completed';
  notes?: string;
  tags?: string[];
}

/** Task list */
export interface TaskList {
  list_id: string;
  name: string;
  description?: string;
  items: TaskItem[];
  created_at?: string;
  updated_at?: string;
}

/** Add tasks from text request */
export interface AddTasksFromTextRequest {
  text: string;
}

/** Add tasks from text response */
export interface AddTasksFromTextResponse {
  success: boolean;
  list_id?: string;
  added_items?: TaskItem[];
  message?: string;
}

/** Calendar event */
export interface CalendarEvent {
  event_id: string;
  title: string;
  start_time: string;
  end_time?: string;
  duration_minutes?: number;
  location?: string;
  description?: string;
  attendees?: string[];
  status?: string;
}

/** Event from text request */
export interface EventFromTextRequest {
  text: string;
  auto_create?: boolean;
}

/** Event from text response */
export interface EventFromTextResponse {
  success: boolean;
  created_event_ids?: string[];
  parsed_events?: Record<string, unknown>[];
  needs_confirmation?: boolean;
  ambiguities?: string[];
  message?: string;
}

/** Wishlist item */
export interface WishlistItem {
  item_id: string;
  description: string;
  target_price?: number;
  category?: string;
  added_at?: string;
}

/** Add to wishlist request */
export interface AddWishlistRequest {
  description: string;
  target_price?: number;
  category?: string;
}

/** Deal match */
export interface Deal {
  deal_id?: string;
  title: string;
  description?: string;
  store?: string;
  url?: string;
  original_price?: number;
  sale_price?: number;
  discount_percent?: number;
  relevance_score?: number;
  matching_preferences?: string[];
}

/** Deal search request */
export interface DealSearchRequest {
  query?: string;
  category?: string;
  max_results?: number;
}

/** Deal search response */
export interface DealSearchResponse {
  deals: Deal[];
  total_found?: number;
  query_used?: string;
}

/** Reservation */
export interface Reservation {
  reservation_id: string;
  reservation_type: 'restaurant' | 'appointment' | 'service' | 'other';
  venue_name?: string;
  datetime: string;
  party_size?: number;
  notes?: string;
  status?: 'pending' | 'confirmed' | 'cancelled';
  created_at?: string;
}

/** Create reservation request */
export interface CreateReservationRequest {
  reservation_type: string;
  venue_name?: string;
  datetime: string;
  party_size?: number;
  notes?: string;
}

/** Reservation from text request */
export interface ReservationFromTextRequest {
  text: string;
}

/** Reservation result */
export interface ReservationResult {
  success: boolean;
  reservation_id?: string;
  venue_name?: string;
  datetime?: string;
  party_size?: number;
  notes?: string;
  status?: string;
  action_required?: string;
  message?: string;
}

/** Generated document */
export interface GeneratedDocument {
  doc_id: string;
  doc_type: string;
  title: string;
  content?: string;
  format?: string;
  created_at: string;
}

/** Document generation request */
export interface DocumentGenerateRequest {
  doc_type: 'process' | 'checklist' | 'template' | 'sop' | 'agenda';
  topic: string;
  context?: Record<string, unknown>;
}
